"""Shared, dependency-free settings used by the terminal and Windows desktop."""
from __future__ import annotations

import copy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

from agent_names import SLOTS, display_names
from model_http import request

BASE = Path(__file__).resolve().parent
ROLES = ('Implementación', 'Revisión', 'Pruebas')


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'Se esperaba un objeto JSON en {path}.')
    return value


def find_llama():
    found = shutil.which('llama-server.exe') or shutil.which('llama-server')
    if found:
        return found
    root = Path(os.environ.get('LOCALAPPDATA', '.'))/'Microsoft'/'WinGet'/'Packages'
    return next((str(p) for p in root.glob('ggml.llamacpp_*/llama-server.exe')), '')


def profile_path(config, config_path):
    value = Path(config.get('coding', {}).get('server_profiles_path', 'server_profiles.json'))
    return value if value.is_absolute() else Path(config_path).resolve().parent/value


def snapshot(config_path):
    """Never create files, launch models, or contact endpoints while loading the UI."""
    path = Path(config_path).resolve()
    config = read_json(path) if path.exists() else {'agents': {}, 'coding': {}, 'model_compat': {}}
    profiles_file = profile_path(config, path)
    profiles = read_json(profiles_file) if profiles_file.exists() else {}
    labels = display_names(config) if config.get('agents') else dict(zip(SLOTS, ('Builder', 'Reviewer', 'Tester')))
    agents = []
    for index, slot in enumerate(SLOTS):
        profile = profiles.get(slot, {})
        model = profile.get('model', '')
        if model and not Path(model).is_absolute():
            model = str((profiles_file.parent/model).resolve())
        agents.append({'slot': slot, 'name': labels[slot], 'role': ROLES[index],
                       'url': config.get('agents', {}).get(slot, {}).get('url', f'http://127.0.0.1:{8081+index}'),
                       'family': 'gemma2' if config.get('model_compat', {}).get(slot) == 'gemma2' else 'native',
                       'model': model, 'device': profile.get('device', 'Vulkan0')})
    return {'exists': path.exists(), 'config_path': str(path), 'agents': agents,
            'load_on_demand': bool(config.get('coding', {}).get('load_on_demand', False)),
            'llama_server_path': config.get('coding', {}).get('llama_server_path', '') or find_llama(),
            'workspace_mode': config.get('setup', {}).get('workspace_mode', 'folder'),
            'wsl_distro': config.get('setup', {}).get('wsl_distro', 'AgentLab-Repair')}


def endpoint(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise ValueError('URL inválida; ejemplo: http://127.0.0.1:8081')
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('El puerto de la URL debe estar entre 1 y 65535.') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or port == 0 or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path.rstrip('/')):
        raise ValueError('Usa la URL base HTTP(S), sin credenciales ni /v1: http://127.0.0.1:8081')
    return value.rstrip('/')


def prepare(draft, config_path):
    """Validate the entire draft before writing; preserve unrelated user settings."""
    path = Path(config_path).resolve()
    if not isinstance(draft, dict):
        raise ValueError('La configuración debe ser un objeto JSON con los ajustes del equipo.')
    config = read_json(path) if path.exists() else {'agents': {}, 'coding': {}, 'model_compat': {}}
    config = copy.deepcopy(config)
    agents = draft.get('agents')
    if not isinstance(agents, list) or len(agents) != 3 or {a.get('slot') for a in agents if isinstance(a, dict)} != set(SLOTS):
        raise ValueError('Se necesitan exactamente los tres agentes del equipo.')
    if not isinstance(draft.get('load_on_demand'), bool):
        raise ValueError('Elige servidores existentes o carga local por turnos.')
    local = draft['load_on_demand']
    if local and os.name != 'nt':
        raise ValueError('La carga automática local necesita Windows. Usa servidores existentes en Linux/macOS.')
    config.setdefault('coding', {}).setdefault('max_reply_tokens', 1800)
    config['coding'].setdefault('model_timeout', 300)
    config['coding']['load_on_demand'] = local
    config.setdefault('agents', {})
    config.setdefault('model_compat', {})
    profiles_file = profile_path(config, path)
    if profiles_file == path:
        raise ValueError('La configuración y los perfiles deben ser archivos distintos.')
    profiles = read_json(profiles_file) if local and profiles_file.exists() else {}
    for agent in agents:
        slot = agent['slot']
        config['agents'].setdefault(slot, {})
        config['agents'][slot]['display_name'] = agent.get('name', '')
        url = endpoint(agent.get('url', ''))
        if local:
            port = 8081 + SLOTS.index(slot)
            if url not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                raise ValueError('La carga por turnos usa 127.0.0.1 en los puertos 8081, 8082 y 8083.')
        config['agents'][slot]['url'] = url
        family = agent.get('family', 'native')
        if family not in ('native', 'gemma2'):
            raise ValueError('Familia de modelo desconocida.')
        if family == 'gemma2':
            config['model_compat'][slot] = 'gemma2'
        else:
            config['model_compat'].pop(slot, None)
        if local:
            model = Path(str(agent.get('model', '')).strip().strip('"')).expanduser()
            if not model.is_absolute():
                model = path.parent/model
            if not model.is_file() or model.suffix.lower() != '.gguf' or '"' in str(model):
                raise ValueError(f'{agent.get("name", slot)}: selecciona un archivo .gguf existente.')
            device = str(agent.get('device', '')).strip()
            if not re.fullmatch(r'[A-Za-z0-9_:.,-]+', device):
                raise ValueError('Dispositivo inválido. Ejemplos: Vulkan0, CUDA0 o none para CPU.')
            previous = profiles.setdefault(slot, {})
            previous.update(model=str(model.resolve()), device=device)
            # Keep custom template arguments when the family has not changed.
            old_family = 'gemma2' if '--chat-template' in previous.get('template_args', []) and 'gemma' in previous.get('template_args', []) else 'native'
            if not previous.get('template_args') or old_family != family:
                previous['template_args'] = ['--no-jinja', '--chat-template', 'gemma'] if family == 'gemma2' else ['--jinja']
    display_names(config)
    if local:
        executable = str(draft.get('llama_server_path', '')).strip().strip('"') or find_llama()
        if not executable or not Path(executable).is_file() or Path(executable).suffix.lower() != '.exe':
            raise ValueError('Selecciona llama-server.exe. Puedes instalar llama.cpp con WinGet o descargar su versión para Windows.')
        config['coding']['llama_server_path'] = str(Path(executable).resolve())
        config['coding']['server_profiles_path'] = str(profiles_file)
    mode = draft.get('workspace_mode', 'folder')
    distro = draft.get('wsl_distro', 'AgentLab-Repair')
    if mode not in ('folder', 'wsl') or not isinstance(distro, str) or not re.fullmatch(r'AgentLab-[A-Za-z0-9_-]+', distro):
        raise ValueError('El WSL dedicado debe llamarse AgentLab- seguido de letras, números, _ o -.')
    if mode == 'wsl' and os.name != 'nt':
        raise ValueError('La administración de WSL necesita Windows; elige carpeta en este sistema.')
    config.setdefault('setup', {}).update(workspace_mode=mode, wsl_distro=distro)
    return config, profiles, profiles_file


def save(draft, config_path):
    config, profiles, profiles_file = prepare(draft, config_path)
    path = Path(config_path).resolve()
    targets = [(profiles_file, profiles), (path, config)] if draft['load_on_demand'] else [(path, config)]
    old, staged, backups = {}, {}, []
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    try:
        for target, data in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            old[target] = target.read_bytes() if target.exists() else None
            if old[target] is not None:
                backup = target.with_name(target.name+'.'+stamp+'.bak')
                backup.write_bytes(old[target])
                backups.append(str(backup))
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, prefix=target.name+'.', suffix='.tmp', delete=False) as output:
                staged[target] = Path(output.name)
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write('\n')
        published = []
        try:
            for target, _ in targets:
                staged[target].replace(target)
                published.append(target)
        except OSError:
            for target in reversed(published):
                if old[target] is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(old[target])
            raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return {'saved': str(path), 'backups': backups,
            'message': 'Configuración guardada. Comprueba las conexiones antes de reparar.'}


def diagnose(config_path):
    draft = snapshot(config_path)
    checks = [{'name': 'Configuración', 'ok': draft['exists'], 'detail': str(Path(config_path).resolve())}]
    if draft['load_on_demand']:
        try:
            prepare(draft, config_path)
            checks.append({'name': 'Modelos locales', 'ok': True, 'detail': 'Archivos y lanzador disponibles. Se cargarán al reparar; no se han iniciado modelos.'})
        except (ValueError, OSError) as exc:
            checks.append({'name': 'Modelos locales', 'ok': False, 'detail': str(exc)})
    else:
        for agent in draft['agents']:
            try:
                health = request(endpoint(agent['url'])+'/health', timeout=3)
                ok = health.get('status') == 'ok'
                detail = 'Servidor disponible. La sesión comprobará el chat con gramática GBNF.' if ok else 'El servidor aún no está listo.'
            except (OSError, ValueError, RuntimeError) as exc:
                ok, detail = False, str(exc)
            checks.append({'name': agent['name'], 'ok': ok, 'detail': detail})
    if draft['workspace_mode'] == 'wsl':
        try:
            from repair_workspace import WSLWorkspace
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as run:
                WSLWorkspace(draft['wsl_distro'], '/workspace', Path(run))
            checks.append({'name': 'WSL dedicado', 'ok': True, 'detail': 'Distribución administrada y ajustes de aislamiento comprobados.'})
        except (OSError, ValueError, RuntimeError) as exc:
            checks.append({'name': 'WSL dedicado', 'ok': False, 'detail': str(exc)})
    return {'ready': all(c['ok'] for c in checks), 'checks': checks}


def provision_wsl(distro):
    if os.name != 'nt' or not re.fullmatch(r'AgentLab-[A-Za-z0-9_-]+', distro):
        raise ValueError('WSL requiere Windows y un nombre AgentLab- válido.')
    shell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    if not shell or not shutil.which('wsl.exe'):
        raise ValueError('Instala WSL desde Windows y reinicia antes de preparar el entorno dedicado.')
    # Inherits the terminal, or the desktop's regular output pipe. No new window.
    return subprocess.call([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                            str(BASE/'setup_repair_wsl.ps1'), '-Name', distro],
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
