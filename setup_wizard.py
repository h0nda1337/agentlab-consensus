"""Friendly terminal setup, also exposed as a JSON bridge for the WPF client."""
import json
import os
from pathlib import Path
import sys

from agent_names import display_names
from setup_service import SLOTS, snapshot, endpoint, save, diagnose, provision_wsl, prepare


def interactive(config_path, ask=input, emit=print):
    def question(label, default=''):
        answer = ask(f'{label}'+(f' [{default}]' if default else '')+': ').strip()
        return answer or default

    def choice(label, options, default='1'):
        emit(label)
        for key, description in options:
            emit(f'  {key}. {description}')
        while True:
            answer = question('Elige una opción', default)
            if answer in dict(options):
                return answer
            emit('Escribe uno de los números de la lista.')

    def file_question(label, default, suffix):
        while True:
            value = question(label, default).strip('"')
            file = Path(value).expanduser()
            if not file.is_absolute():
                file = Path(config_path).resolve().parent/file
            if file.is_file() and file.suffix.lower() == suffix and '"' not in value:
                return str(file.resolve())
            emit(f'No se encontró un archivo {suffix}. Copia su ruta completa o pulsa Ctrl+C para salir.')

    try:
        draft = snapshot(config_path)
        emit('\nAGENTLAB CONSENSUS · Asistente de configuración')
        emit('Tres agentes colaboran para reparar código y verificarlo con pruebas.')
        emit('Enter conserva el valor entre corchetes. Ctrl+C sale sin guardar.\n')
        emit('1 de 4 · Tu equipo')
        while True:
            for agent in draft['agents']:
                agent['name'] = question(f'Nombre de quien se ocupa de {agent["role"].lower()}', agent['name'])
            try:
                display_names({'agents': {a['slot']: {'display_name': a['name']} for a in draft['agents']}})
                break
            except ValueError as exc:
                emit(str(exc))
        emit('\n2 de 4 · Modelos')
        modes = [('1', 'Servidores llama.cpp ya instalados y en ejecución')]
        if os.name == 'nt':
            modes.append(('2', 'Archivos GGUF locales: cargar un modelo por turno (Windows, menos RAM)'))
        mode = choice('¿Cómo usarás tus modelos?', modes, '2' if draft['load_on_demand'] and os.name == 'nt' else '1')
        draft['load_on_demand'] = mode == '2'
        if mode == '2':
            emit('Necesitas llama-server.exe y tus tres archivos GGUF. No se descargarán modelos.')
            draft['llama_server_path'] = file_question('Ruta de llama-server.exe', draft['llama_server_path'], '.exe')
        for index, agent in enumerate(draft['agents']):
            emit(f'\n{agent["name"]} · {agent["role"]}')
            if mode == '1':
                while True:
                    try:
                        agent['url'] = endpoint(question('URL base del servidor (sin /v1)', agent['url']))
                        break
                    except ValueError as exc:
                        emit(str(exc))
            else:
                agent['url'] = f'http://127.0.0.1:{8081+index}'
                agent['model'] = file_question('Ruta del archivo .gguf', agent['model'], '.gguf')
                agent['device'] = question('Dispositivo (Vulkan0, CUDA0 o none para CPU)', agent['device'])
            family = choice('Plantilla del modelo', [('1', 'Nativa del GGUF (Qwen, Llama, Mistral...)'),
                            ('2', 'Gemma 2')], '2' if agent['family'] == 'gemma2' else '1')
            agent['family'] = 'gemma2' if family == '2' else 'native'
        emit('\n3 de 4 · Entorno de trabajo')
        environments = [('1', 'Carpeta: reparar una copia y revisar antes de aplicar')]
        if os.name == 'nt':
            environments.append(('2', 'WSL dedicado: Linux con acceso root completo'))
        mode = choice('¿Dónde quieres comenzar?', environments, '2' if draft['workspace_mode'] == 'wsl' and os.name == 'nt' else '1')
        draft['workspace_mode'] = 'wsl' if mode == '2' else 'folder'
        if mode == '2':
            draft['wsl_distro'] = question('Nombre de la distribución', draft['wsl_distro'])
            emit('Los cambios WSL son directos y root puede modificar todo Linux. No es una VM de seguridad.')
        emit('\n4 de 4 · Revisar y guardar')
        for agent in draft['agents']:
            emit(f'  {agent["name"]}: {agent["role"]} · {agent["url"]} · {agent["family"]}')
        emit(f'  Destino: {draft["workspace_mode"]} · Configuración: {Path(config_path).resolve()}')
        prepare(draft, config_path)
        if choice('¿Guardar esta configuración?', [('1', 'Guardar (respalda la configuración anterior)'), ('2', 'Salir sin guardar')]) == '2':
            emit('Cancelado. No se ha cambiado tu configuración.')
            return 0
        result = save(draft, config_path)
        emit(result['message'])
        if draft['workspace_mode'] == 'wsl':
            if choice('Preparar WSL ahora puede descargar Debian y paquetes (varios minutos).',
                      [('1', 'Prepararlo después'), ('2', 'Preparar únicamente esta distribución AgentLab')]) == '2':
                code = provision_wsl(draft['wsl_distro'])
                if code:
                    emit('La configuración está guardada; WSL aún necesita preparación. Revisa el mensaje anterior.')
                    return code
        if choice('¿Comprobar conexiones sin iniciar modelos?', [('1', 'Comprobar'), ('2', 'Hacerlo después')]) == '1':
            report = diagnose(config_path)
            for check in report['checks']:
                emit(f'  {"OK" if check["ok"] else "PENDIENTE"} · {check["name"]}: {check["detail"]}')
        emit('\nSiguiente paso: abre Start-Desktop.cmd o ejecuta una reparación desde la terminal.')
        emit(f'python agentlab.py --config "{Path(config_path).resolve()}" '+
             (f'wsl --distro "{draft["wsl_distro"]}" --path /workspace/mi-proyecto' if draft['workspace_mode'] == 'wsl' else 'folder "C:/mi-proyecto"')+
             ' --task "Describe el arreglo" --test "'+('python3' if draft['workspace_mode'] == 'wsl' else 'python')+' -m unittest -v"')
        return 0
    except (EOFError, KeyboardInterrupt):
        emit('\nAsistente cerrado. Los cambios sin guardar se descartaron.')
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        emit(f'No se pudo completar la configuración: {exc}')
        emit('Vuelve a ejecutar python agentlab.py setup para corregir los datos.')
        return 2


def run_setup(args):
    try:
        if args.snapshot:
            print(json.dumps(snapshot(args.config), ensure_ascii=False))
        elif args.save_json:
            print(json.dumps(save(json.load(sys.stdin), args.config), ensure_ascii=False))
        elif args.check:
            result = diagnose(args.config)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ready'] else 1
        elif args.prepare_wsl:
            return provision_wsl(args.prepare_wsl)
        else:
            return interactive(args.config)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
