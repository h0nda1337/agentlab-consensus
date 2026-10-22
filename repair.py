"""CLI for collaborative code/folder and dedicated root WSL repairs."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import uuid
from contextlib import ExitStack

from repair_team import CodingModels, RepairTeam
from repair_workspace import FolderWorkspace, WSLWorkspace, target_lock
from agent_names import SLOTS, display_names, update_names

BASE = Path(__file__).resolve().parent
DEFAULT_RUNS = (Path(os.environ['LOCALAPPDATA'])/'AgentLab'/'repairs'
                if os.name == 'nt' and os.environ.get('LOCALAPPDATA') else BASE/'work'/'repairs')


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Equipo de tres agentes para reparar software con consenso y pruebas reales.')
    parser.add_argument('--config', type=Path, default=BASE/'config.json')
    parser.add_argument('--runs', type=Path, default=DEFAULT_RUNS, help='Carpeta de sesiones y copias (Windows: %%LOCALAPPDATA%%/AgentLab/repairs)')
    subparsers = parser.add_subparsers(dest='mode', required=True)
    names_parser = subparsers.add_parser('agents', help='Ver o cambiar los nombres del equipo')
    name_actions = names_parser.add_subparsers(dest='name_action', required=True)
    name_actions.add_parser('list', help='Mostrar nombres actuales y roles')
    rename_parser = name_actions.add_parser('rename', help='Cambiar un solo nombre')
    rename_parser.add_argument('agent', help='Nombre actual o identificador interno')
    rename_parser.add_argument('new_name')
    all_names_parser = name_actions.add_parser('names', help='Cambiar los tres: implementación, revisión y pruebas')
    all_names_parser.add_argument('names', nargs=3)
    for mode in ('folder', 'wsl'):
        sub = subparsers.add_parser(mode, help='Copia de carpeta' if mode == 'folder' else 'Acceso root al WSL dedicado')
        if mode == 'folder':
            sub.add_argument('path', type=Path, help='Carpeta original')
            sub.add_argument('--apply', action='store_true', help='Aplicar al original solo tras pruebas y consenso final')
        else:
            sub.add_argument('--distro', default='AgentLab-Repair')
            sub.add_argument('--path', default='/workspace', help='Directorio Linux de trabajo; root conserva acceso a todo el WSL')
        sub.add_argument('--task', required=True, help='Objetivo compartido del equipo')
        sub.add_argument('--test', required=True, help='Comando de verificación que debe pasar al terminar')
        sub.add_argument('--max-steps', type=int, default=36)
        sub.add_argument('--timeout', type=int, default=120, help='Segundos por comando')
    args = parser.parse_args(argv)
    if args.mode != 'agents' and (not 1 <= args.max_steps <= 500 or not 1 <= args.timeout <= 3600):
        parser.error('--max-steps: 1..500; --timeout: 1..3600')
    if args.mode != 'agents' and (not args.task.strip() or not args.test.strip()):
        parser.error('--task y --test no pueden estar vacíos')
    run_dir = args.runs.resolve() / (datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    locks = ExitStack()
    models = None
    try:
        cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
        if args.mode == 'agents':
            names = display_names(cfg)
            if args.name_action == 'names':
                names = update_names(cfg, dict(zip(SLOTS, args.names)), args.config)
            elif args.name_action == 'rename':
                matched = [slot for slot in SLOTS if args.agent.casefold() in (slot.casefold(), names[slot].casefold())]
                if len(matched) != 1:
                    raise ValueError('Nombre desconocido o ambiguo; usa agents list para ver los identificadores.')
                names = update_names(cfg, {matched[0]:args.new_name}, args.config)
            for slot, role in zip(SLOTS, ('implementación', 'revisión', 'pruebas')):
                print(f'{names[slot]} — {role} (id: {slot})')
            return 0
        models = CodingModels(cfg)
        models.check_health()
        lock_dir = BASE/'work'/'repair-locks'
        identity = str(args.path.resolve()) if args.mode == 'folder' else 'wsl:'+args.distro
        locks.enter_context(target_lock(lock_dir, identity))
        run_dir.mkdir(parents=True, exist_ok=False)
        if args.mode == 'folder':
            workspace = FolderWorkspace(args.path, run_dir, excluded=[args.runs.resolve(), lock_dir])
        else:
            workspace = WSLWorkspace(args.distro, args.path, run_dir)
        print(f'Sesión: {run_dir}\n{workspace.description}', flush=True)
        team = RepairTeam(workspace, models, args.task, args.test, run_dir,
                          max_steps=args.max_steps, command_timeout=args.timeout,
                          emit=lambda message: print(message, flush=True))
        result = team.run()
        if result['status'] == 'verified' and args.mode == 'folder' and args.apply:
            try:
                workspace.publish(result['approved_fingerprint'])
                result['applied'] = True
                team._save()
            except Exception as exc:
                result.update(status='publish_failed', reason=str(exc))
                team._save()
        destination = (f"aplicado a la carpeta original: {result['applied']}" if args.mode == 'folder'
                       else 'modo directo: los cambios se conservan dentro del WSL')
        print(f"\nEstado: {result['status']}; {destination}\nResultados: {run_dir}", flush=True)
        if result.get('reason'):
            print(result['reason'])
        return 0 if result['status'] == 'verified' else 1
    except (ValueError, RuntimeError, OSError) as exc:
        if run_dir.exists():
            (run_dir/'startup_error.json').write_text(json.dumps({'status':'failed','reason':str(exc)}, ensure_ascii=False), encoding='utf-8')
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    finally:
        if models:
            try:
                models.close()
            except Exception as exc:
                print(f'No se pudo cerrar un servidor de esta sesión: {exc}', file=sys.stderr)
        locks.close()


if __name__ == '__main__':
    raise SystemExit(main())
