"""File tools and command runners for collaborative repairs. No roleplay state."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager

IGNORED = {'.git', '.venv', 'venv', 'node_modules', '__pycache__',
           '.pytest_cache', '.mypy_cache', '.ruff_cache', '.agentlab'}
MAX_FILE = 2 * 1024 * 1024


@contextmanager
def target_lock(lock_dir, identity):
    """OS-owned lock, released even when a repair process crashes."""
    lock_dir = Path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / (hashlib.sha256(identity.casefold().encode()).hexdigest()+'.lock')
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('Ya hay otra reparación de AgentLab activa sobre este destino.') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def is_link(path):
    """Also reject NTFS junctions/reparse points on Python 3.11."""
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def resolve_file(root, path, full_access=False):
    root = Path(root).resolve()
    if not isinstance(path, str) or '\x00' in path:
        raise ValueError('Ruta inválida.')
    raw = Path(path or '.')
    checked_parts = raw.parts[1:] if raw.anchor else raw.parts
    if os.name == 'nt' and any(
        ':' in p or
        p.endswith((' ', '.')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p)
        for p in checked_parts if p not in ('', '.', '..')
    ):
        raise ValueError('Ruta especial o nombre de archivo no permitido.')
    if not full_access and ('..' in raw.parts or '.git' in raw.parts):
        raise ValueError('La ruta debe permanecer dentro de la carpeta de trabajo.')
    candidate = raw if raw.is_absolute() else root / raw
    # Check BEFORE resolving, otherwise an internal link disappears from view.
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current.exists() or current.is_symlink():
            if is_link(current):
                raise ValueError('No se siguen enlaces ni junctions en las herramientas de archivos.')
    resolved = candidate.resolve()
    if not full_access and not resolved.is_relative_to(root):
        raise ValueError('Ruta fuera de la carpeta de trabajo.')
    return resolved


def files_in(root, excluded=()):
    root = Path(root).resolve()
    excluded = {Path(p).resolve() for p in excluded}
    count = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED
                         and Path(parent, d).resolve() not in excluded
                         and not is_link(Path(parent, d)))
        for name in sorted(files):
            path = Path(parent, name)
            if is_link(path):
                continue
            count += 1
            if count > 20000:
                raise ValueError('Más de 20000 archivos; selecciona una carpeta más concreta.')
            yield path


def file_tool(root, proposal, full_access=False, dry_run=False):
    tool = proposal['tool']
    path = resolve_file(root, proposal.get('path', ''), full_access)
    if tool in ('list', 'search'):
        if not path.is_dir():
            raise ValueError('Se esperaba una carpeta.')
        rows = []
        for entry in files_in(path):
            relative = entry.relative_to(path).as_posix()
            if tool == 'list':
                rows.append(f'{relative} ({entry.stat().st_size} bytes)')
            elif entry.stat().st_size <= MAX_FILE:
                try:
                    content = entry.read_text(encoding='utf-8-sig')
                except (UnicodeError, OSError):
                    continue
                for number, line in enumerate(content.splitlines(), 1):
                    if proposal.get('search', '') in line:
                        rows.append(f'{relative}:{number}: {line[:500]}')
            if len(rows) >= 160:
                rows = rows[:160] + ['[Listado limitado; elige una subcarpeta o una búsqueda más precisa.]']
                break
        return '\n'.join(rows)[:16000] or '(sin resultados)'
    if tool == 'read':
        if path.stat().st_size > MAX_FILE:
            raise ValueError('Archivo mayor de 2 MiB; usa herramientas de consola en WSL.')
        content = path.read_text(encoding='utf-8-sig')
        lines = content.splitlines()
        first = int(proposal.get('line') or '1')
        if first < 1:
            raise ValueError('line empieza en 1.')
        excerpt = '\n'.join(f'{n}: {line}' for n, line in enumerate(lines[first-1:first+159], first))
        return f'{path.name}: {len(lines)} líneas.\n{excerpt[:14000]}'
    if tool not in ('replace', 'write', 'delete'):
        raise ValueError('Herramienta de archivos desconocida.')
    if path.is_dir():
        raise ValueError('Solo se modifican archivos, no carpetas enteras.')
    if path.exists() and path.stat().st_nlink > 1:
        raise ValueError('No se modifican archivos con hardlinks.')
    if tool == 'delete':
        if not path.is_file():
            raise ValueError('El archivo a eliminar no existe.')
        if dry_run:
            return 'Ruta y archivo validados.'
        path.unlink()
        return 'Archivo eliminado.'
    content = proposal.get('content', '')
    if tool == 'replace':
        original = path.read_bytes().decode('utf-8')
        old = proposal.get('search', '')
        if not old or original.count(old) != 1:
            raise ValueError('replace necesita search exacto con una sola coincidencia; vuelve a leer el archivo.')
        content = original.replace(old, content, 1)
    if dry_run:
        return 'Ruta y contenido validados.'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.agentlab-' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(content.encode('utf-8'))
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return 'Archivo actualizado.'


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def digest_tree(root):
    return {p.relative_to(root).as_posix(): file_hash(p)
            for p in files_in(root)}


def changed_files(before, after):
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def run_process(argv, *, cwd, timeout, log_path, input_data=None):
    """Spool output to disk and kill the process tree on timeout/interrupt."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    with log_path.open('wb') as output:
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'),
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                   start_new_session=os.name != 'nt')
        try:
            process.communicate(input=input_data, timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            timed_out = isinstance(exc, subprocess.TimeoutExpired)
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            if not timed_out:
                raise
    with log_path.open('rb') as output:
        size = log_path.stat().st_size
        head = output.read(4000)
        if size > 8000:
            output.seek(-4000, 2)
            data = head + b'\n[... salida completa en el log ...]\n' + output.read(4000)
        else:
            data = head + output.read()
    return {'exit_code': 124 if timed_out else process.returncode, 'timeout': timed_out,
            'seconds': round(time.monotonic()-started, 2),
            'output': data.decode('utf-8', errors='replace'), 'log': str(log_path)}


class FolderWorkspace:
    full_access = False

    def __init__(self, source, run_dir, excluded=()):
        self.source = Path(source).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.root = self.run_dir / 'workspace'
        self.original = self.run_dir / 'original'
        if not self.source.is_dir() or self.source == Path(self.source.anchor):
            raise ValueError('Selecciona una carpeta de proyecto existente, no la raíz del disco.')
        if self.source.is_relative_to(self.run_dir):
            raise ValueError('El origen no puede estar dentro de esta ejecución.')
        self.root.mkdir(parents=True, exist_ok=False)
        self.original.mkdir()
        paths = list(files_in(self.source, [self.run_dir, *excluded]))
        needed = sum(p.stat().st_size for p in paths)*2 + 16*1024*1024
        if shutil.disk_usage(self.run_dir).free < needed:
            raise ValueError('Espacio insuficiente para crear copia y respaldo; usa --runs en otro disco.')
        for path in paths:
            relative = path.relative_to(self.source)
            original, working = self.original / relative, self.root / relative
            original.parent.mkdir(parents=True, exist_ok=True)
            working.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, original)
            shutil.copy2(original, working)
        self.before = digest_tree(self.original)

    @property
    def description(self):
        return f'Copia de {self.source}. Shell local PowerShell del usuario; cwd={self.root}. Usa path relativo a cwd.'

    def tool(self, proposal):
        return file_tool(self.root, proposal)

    def check_mutation(self, proposal):
        return file_tool(self.root, proposal, dry_run=True)

    def command(self, command, timeout, log_path):
        if os.name == 'nt':
            argv = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                    "$ErrorActionPreference='Stop'; " + command +
                    '; if (-not $?) { exit 1 }; if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }']
        else:
            argv = ['bash', '-lc', command]
        return run_process(argv, cwd=self.root, timeout=timeout, log_path=log_path)

    def changes(self):
        after = digest_tree(self.root)
        names = changed_files(self.before, after)
        diff = []
        for name in names:
            old, new = self.original / name, self.root / name
            if any(p.exists() and p.stat().st_size > MAX_FILE for p in (old, new)):
                diff.append(f'File changed (over 2 MiB, inspect separately): {name}\n')
                continue
            try:
                a = old.read_text(encoding='utf-8').splitlines(keepends=True) if old.exists() else []
                b = new.read_text(encoding='utf-8').splitlines(keepends=True) if new.exists() else []
                diff.extend(difflib.unified_diff(a, b, fromfile='a/'+name, tofile='b/'+name))
            except UnicodeError:
                diff.append(f'Binary file changed: {name}\n')
        return {'files': names, 'fingerprint': hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest(),
                'diff': ''.join(diff)}

    def publish(self, approved_fingerprint):
        changes = self.changes()
        if changes['fingerprint'] != approved_fingerprint:
            raise ValueError('La copia cambió después del consenso final; no se publicará.')
        # Validate every destination before writing any of them.
        for name in changes['files']:
            target = resolve_file(self.source, name)
            if target.exists() and (not target.is_file() or target.stat().st_nlink > 1):
                raise ValueError(f'Destino no publicable: {name}')
            actual = file_hash(target) if target.exists() else None
            if actual != self.before.get(name):
                raise ValueError(f'Conflicto: el original cambió durante la reparación: {name}')
        completed = []
        try:
            for name in changes['files']:
                target = resolve_file(self.source, name)
                replacement = resolve_file(self.root, name)
                if target.exists():
                    backup = self.run_dir / 'backups' / name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                completed.append(name)
                if replacement.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(replacement, target)
                else:
                    target.unlink()
        except Exception:
            for name in reversed(completed):
                target = resolve_file(self.source, name)
                backup = self.run_dir / 'backups' / name
                if backup.exists():
                    shutil.copy2(backup, target)
                else:
                    target.unlink(missing_ok=True)
            raise
        return changes['files']


class WSLWorkspace:
    """Root tools in an explicitly managed distro. WSL is not a hostile-code VM."""
    full_access = True

    def __init__(self, distro='AgentLab-Repair', root='/workspace', run_dir=None):
        if not re.fullmatch(r'AgentLab-[A-Za-z0-9_-]+', distro):
            raise ValueError('Usa una distribución dedicada AgentLab-*. Ejecuta setup_repair_wsl.ps1.')
        if not PurePosixPath(root).is_absolute() or '\x00' in root:
            raise ValueError('El directorio WSL debe ser una ruta Linux absoluta.')
        self.distro, self.root = distro, root
        self.run_dir = Path(run_dir or '.')
        self.wsl = shutil.which('wsl.exe')
        if not self.wsl:
            raise ValueError('wsl.exe no está disponible.')
        check = self._python("""import configparser, json, os
from pathlib import Path
cfg=configparser.ConfigParser(); cfg.read('/etc/wsl.conf')
marker=Path('/etc/agentlab-repair.json')
assert marker.exists() and json.loads(marker.read_text()).get('kind')=='agentlab-repair-v1', 'Falta marca de WSL administrado'
assert not cfg.getboolean('automount','enabled',fallback=True), 'Automount debe estar desactivado'
assert not cfg.getboolean('automount','mountFsTab',fallback=True), 'mountFsTab debe estar desactivado'
assert not cfg.getboolean('interop','enabled',fallback=True), 'Interop debe estar desactivado'
assert not cfg.getboolean('interop','appendWindowsPath',fallback=True), 'Windows PATH debe estar desactivado'
mounts=Path('/proc/mounts').read_text().splitlines()
assert not any('drvfs' in s.lower() or (len(s.split())>2 and s.split()[2]=='9p' and 'aname=drvfs' in s) for s in mounts), 'Hay discos Windows montados'
# The kernel's MZ binfmt registration can remain present with interop=false.
# Actual launch capability is per-distro and no interop socket is exported here.
assert not os.environ.get('WSL_INTEROP'), 'La sesión aún expone un socket Interop; reinicia la distribución'
Path(__import__('sys').argv[1]).mkdir(parents=True,exist_ok=True)
print('OK')""", [root])
        if check.strip() != 'OK':
            raise ValueError('No se pudo validar el entorno WSL dedicado.')
        self.before = self._snapshot()

    @property
    def description(self):
        return f'WSL {self.distro}; usuario root, acceso Linux completo, cwd={self.root}; bash. Windows automount/interop desactivados.'

    def _prefix(self):
        return [self.wsl, '--distribution', self.distro, '--user', 'root', '--cd', '/', '--exec']

    def _python(self, code, arguments=(), payload=None):
        result = subprocess.run(self._prefix()+['python3', '-c', code, *arguments],
                                input=payload, capture_output=True, timeout=45,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            message = result.stderr.decode('utf-8', errors='replace')[-1500:]
            raise RuntimeError(f'WSL {self.distro}: {message or "comando fallido; comprueba la instalación"}')
        return result.stdout.decode('utf-8')

    def tool(self, proposal):
        # Same audited file tools on both systems; no Windows drives or shared SSH.
        source = Path(__file__).read_text(encoding='utf-8')
        worker = source + '\nprint(file_tool(sys.argv[1], json.loads(sys.stdin.read()), True))'
        return self._python(worker, [self.root], json.dumps(proposal).encode('utf-8'))

    def check_mutation(self, proposal):
        source = Path(__file__).read_text(encoding='utf-8')
        worker = source + '\nprint(file_tool(sys.argv[1], json.loads(sys.stdin.read()), True, True))'
        return self._python(worker, [self.root], json.dumps(proposal).encode('utf-8'))

    def command(self, command, timeout, log_path):
        import shlex
        argv = self._prefix()+['env', 'PYTHONDONTWRITEBYTECODE=1', 'timeout', '--signal=TERM', '--kill-after=5', str(timeout),
                              'bash', '-lc', 'cd -- '+shlex.quote(self.root)+' && '+command]
        result = run_process(argv, cwd=self.run_dir, timeout=timeout+15, log_path=log_path)
        if result['exit_code'] in (124, 137):
            result['timeout'] = True
        return result

    def _snapshot(self):
        # Only project files are fingerprinted. Arbitrary root system changes are
        # recorded through commands, not represented as a complete OS diff.
        source = Path(__file__).read_text(encoding='utf-8')
        worker = source + '\nprint(json.dumps(digest_tree(Path(sys.argv[1])),sort_keys=True))'
        return json.loads(self._python(worker, [self.root]))

    def changes(self):
        after = self._snapshot()
        return {'files': changed_files(self.before, after),
                'fingerprint': hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest(),
                'diff': '(WSL: se registran archivos cambiados y comandos; los cambios de sistema quedan en esta distribución.)'}
