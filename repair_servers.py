"""Bounded model residency for machines that also run a WSL repair system."""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from repair_workspace import target_lock

BASE = Path(__file__).resolve().parent


class LazyServers:
    def __init__(self, config):
        self.shell = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
        if not self.shell:
            raise ValueError('La carga local por turnos necesita PowerShell en Windows; desactiva coding.load_on_demand para servidores externos.')
        for name, port in (('Dars',8081), ('Rade',8082), ('Miso',8083)):
            if config['agents'][name]['url'].rstrip('/') not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                raise ValueError('Carga por turnos: usa los puertos locales 8081/8082/8083 o desactiva coding.load_on_demand.')
        self.owner = uuid.uuid4().hex
        self.settings = config.get('coding', {})
        self.active = None
        self.locks = ExitStack()
        self.locks.enter_context(target_lock(BASE/'work'/'repair-locks', 'local-model-pool'))

    def _invoke(self, name, stop=False):
        argv = [self.shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(BASE/'start_servers.ps1'),
                '-Agents', name, '-OwnerToken', self.owner]
        for key, flag in (('server_profiles_path', '-ProfilesPath'), ('llama_server_path', '-LlamaServerPath')):
            if self.settings.get(key):
                argv += [flag, str(self.settings[key])]
        argv += ['-Stop'] if stop else ['-LowMemory']
        log_dir = BASE/'work'/'serverlogs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir/f'manager-{self.owner}-{name}-{"stop" if stop else "start"}.log'
        # A background conhost can inherit anonymous capture pipes even when
        # llama-server redirects its own output. Wait for PowerShell, not EOF on
        # descendants' handles; spool diagnostics to a regular file instead.
        with log_path.open('wb') as output:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, timeout=300,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            output = log_path.read_bytes().decode('utf-8', errors='replace')[-3000:]
            raise RuntimeError(f'No se pudo {"liberar" if stop else "cargar"} {name}: {output}')

    def ensure(self, name):
        if self.active == name:
            return
        if self.active:
            self._invoke(self.active, stop=True)
            self.active = None
        # Mark the attempted model too, so startup failures get a cleanup attempt.
        self.active = name
        self._invoke(name)

    def close(self):
        try:
            if self.active:
                self._invoke(self.active, stop=True)
                self.active = None
        finally:
            self.locks.close()
