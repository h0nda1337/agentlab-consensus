"""Setup journeys exercise the real CLI and filesystem without launching models."""
import contextlib
import copy
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from setup_service import snapshot, save, diagnose, endpoint
from setup_wizard import interactive
from repair_servers import LazyServers
import test_repair as repairs

BASE = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root/'equipo con espacios'/'config.json'

    def cli(self, *arguments, input=''):
        return subprocess.run([sys.executable, str(BASE/'agentlab.py'), '--config', str(self.config), 'setup', *arguments],
                              input=input, capture_output=True, text=True, encoding='utf-8', timeout=30,
                              env={**os.environ, 'PYTHONUTF8': '1'})

    def test_cli_wizard_first_run_and_native_families(self):
        # Names, existing servers, URL/family per agent, folder, save, skip check.
        answers = ['Atlas', 'Iris', 'Nova', '1', '', '1', '', '1', '', '2', '1', '1', '2']
        result = self.cli(input='\n'.join(answers)+'\n')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        config = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual([config['agents'][slot]['display_name'] for slot in ('Dars','Rade','Miso')], ['Atlas','Iris','Nova'])
        self.assertEqual(config['model_compat'], {'Miso':'gemma2'})
        self.assertIn('Configuración guardada', result.stdout)
        self.assertFalse((self.config.parent/'server_profiles.json').exists())

    def test_cancel_and_eof_leave_existing_bytes_untouched(self):
        draft = snapshot(self.config)
        save(draft, self.config)
        original = self.config.read_bytes()
        # Save menu: explicitly leave, without writing a backup either.
        result = self.cli(input='\n'.join(['']*11+['2'])+'\n')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(list(self.config.parent.glob('*.bak')), [])
        result = self.cli(input='Atlas\n')
        self.assertEqual(result.returncode, 130)
        self.assertEqual(self.config.read_bytes(), original)

    def test_invalid_duplicate_draft_does_not_write_any_file(self):
        draft = snapshot(self.config)
        draft['agents'][1]['name'] = draft['agents'][0]['name'].upper()
        result = self.cli('--save-json', input=json.dumps(draft))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.config.exists())
        self.assertIn('distintos', json.loads(result.stderr)['error'])

    @unittest.skipUnless(os.name == 'nt', 'Windows WSL setup')
    def test_wsl_wizard_can_defer_install_and_prints_linux_python_command(self):
        answers = iter(['','','','1','','1','','1','','1','2','AgentLab-Example','1','1','2'])
        messages = []
        with patch('setup_wizard.provision_wsl', side_effect=AssertionError('Install was deferred')):
            self.assertEqual(interactive(self.config, ask=lambda _: next(answers), emit=messages.append), 0)
        self.assertIn('--test "python3 -m unittest -v"', messages[-1])
        self.assertIn('--distro "AgentLab-Example"', messages[-1])
        saved = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(saved['setup']['workspace_mode'], 'wsl')

    def test_existing_settings_and_backup_are_preserved(self):
        save(snapshot(self.config), self.config)
        previous = json.loads(self.config.read_text(encoding='utf-8'))
        previous.update(extra={'keep': True})
        previous['agents']['Dars']['temperature'] = 0.42
        previous['coding']['model_timeout'] = 123
        self.config.write_text(json.dumps(previous), encoding='utf-8')
        before = self.config.read_bytes()
        draft = snapshot(self.config)
        draft['agents'][0]['name'] = 'Atenea α'
        result = self.cli('--save-json', input=json.dumps(draft))
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(saved['extra'], {'keep':True})
        self.assertEqual(saved['coding']['model_timeout'], 123)
        self.assertEqual(saved['agents']['Dars']['temperature'], 0.42)
        self.assertEqual(saved['agents']['Dars']['display_name'], 'Atenea α')
        self.assertEqual(Path(json.loads(result.stdout)['backups'][0]).read_bytes(), before)

    def test_invalid_endpoint_explains_base_url_and_reprompts(self):
        for value in ('ftp://host', 'http://user:secret@host', 'http://localhost:99999', 'http://host/v1', 'http://host?key=secret', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                endpoint(value)
        self.assertEqual(endpoint('https://example.com:8443/'), 'https://example.com:8443')
        answers = iter(['','','','1','http://host/v1','http://localhost:9000','1','','1','','1','1','1','2'])
        messages = []
        self.assertEqual(interactive(self.config, ask=lambda _: next(answers), emit=messages.append), 0)
        self.assertIn('sin credenciales', '\n'.join(messages))

    def test_unreachable_servers_are_pending_not_ready(self):
        save(snapshot(self.config), self.config)
        with patch('setup_service.request', side_effect=RuntimeError('Sin conexión')) as transport:
            report = diagnose(self.config)
        self.assertFalse(report['ready'])
        self.assertEqual([c['ok'] for c in report['checks']], [True,False,False,False])
        self.assertEqual(transport.call_count, 3)
        self.assertTrue(all(c.kwargs['timeout'] == 3 for c in transport.call_args_list))

    def test_loading_settings_is_offline_and_missing_config_is_not_ready(self):
        with patch('setup_service.request', side_effect=AssertionError('No network')):
            result = self.cli('--snapshot')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)['exists'])
            self.assertFalse(self.config.exists())
        with patch('setup_service.request', return_value={'status':'ok'}):
            self.assertFalse(diagnose(self.config)['ready'])

    @unittest.skipUnless(os.name == 'nt', 'Windows local launcher')
    def test_local_profiles_paths_family_and_diagnostics_without_starting_models(self):
        draft = snapshot(self.config)
        draft['load_on_demand'] = True
        executable = self.root/'llama-server.exe'
        executable.write_bytes(b'placeholder; never executed')
        draft['llama_server_path'] = str(executable)
        for index, agent in enumerate(draft['agents']):
            model = self.root/f'model {index}.gguf'
            model.write_bytes(b'GGUF')
            agent.update(model=str(model), device='none', family='gemma2' if index == 2 else 'native')
        save(draft, self.config)
        saved = json.loads(self.config.read_text(encoding='utf-8'))
        profiles = json.loads(Path(saved['coding']['server_profiles_path']).read_text(encoding='utf-8'))
        self.assertEqual(profiles['Miso']['template_args'], ['--no-jinja','--chat-template','gemma'])
        self.assertEqual(profiles['Dars']['device'], 'none')
        with patch('setup_service.subprocess.call', side_effect=AssertionError('No model launch')), patch('setup_service.request', side_effect=AssertionError('No network')):
            self.assertTrue(diagnose(self.config)['ready'])
        before = self.config.read_bytes()
        draft['agents'][0]['model'] = str(self.root/'missing.gguf')
        with self.assertRaisesRegex(ValueError, 'gguf'):
            save(draft, self.config)
        self.assertEqual(self.config.read_bytes(), before)

    def test_two_file_save_rolls_back_if_config_publish_fails(self):
        draft = snapshot(self.config)
        save(draft, self.config)
        before = self.config.read_bytes()
        profiles_path = self.config.parent/'server_profiles.json'
        profiles_path.write_text('{"keep":true}', encoding='utf-8')
        profiles_before = profiles_path.read_bytes()
        config_data = json.loads(before)
        replacement = Path.replace
        def fail_config(source, target):
            if Path(target).resolve() == self.config.resolve():
                raise OSError('Simulated config publish failure')
            return replacement(source, target)
        with patch('setup_service.prepare', return_value=(config_data, {'changed':True}, profiles_path)), patch.object(Path, 'replace', fail_config):
            with self.assertRaises(OSError):
                save({**draft,'load_on_demand':True}, self.config)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(profiles_path.read_bytes(), profiles_before)

    def test_saved_wizard_configuration_drives_a_real_cli_repair(self):
        calls = []
        proposals = iter([repairs.action('replace', path='calc.py', search='return a - b', content='return a + b'), repairs.action('finish')])
        class Models(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def answer(self, value):
                data = json.dumps(value).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_GET(self):
                self.answer({'status':'ok'})
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(payload)
                review = 'Revisa la propuesta exacta adjunta.' in payload['messages'][-1]['content']
                value = {'decision':'approve', 'reason':'Verificado con evidencia.'} if review else next(proposals)
                self.answer({'choices':[{'message':{'content':json.dumps(value)}}]})
        server = ThreadingHTTPServer(('127.0.0.1', 0), Models)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            draft = snapshot(self.config)
            for agent in draft['agents']:
                agent['url'] = f'http://127.0.0.1:{server.server_port}'
            save(draft, self.config)
            source = self.root/'source'
            source.mkdir()
            (source/'calc.py').write_text('def add(a, b):\n    return a - b\n', encoding='utf-8')
            (source/'test_calc.py').write_text('import unittest\nfrom calc import add\nclass Tests(unittest.TestCase):\n    def test_sum(self): self.assertEqual(add(2, 3), 5)\n', encoding='utf-8')
            runs = self.root/'runs'
            result = subprocess.run([sys.executable, str(BASE/'agentlab.py'), '--config', str(self.config), '--runs', str(runs),
                                     'folder', str(source), '--apply', '--task', 'Corrige la suma sin debilitar las pruebas',
                                     '--test', 'python -m unittest -q', '--max-steps', '2'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30, env={**os.environ, 'PYTHONUTF8':'1'})
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('return a + b', (source/'calc.py').read_text())
            state = json.loads(next(runs.glob('*/result.json')).read_text(encoding='utf-8'))
            self.assertEqual(state['status'], 'verified')
            self.assertTrue(state['applied'])
            self.assertEqual(len(calls), 8)  # Two proposals and six independent votes.
            self.assertTrue(all('grammar' in call for call in calls))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class DesktopCancellationTests(unittest.TestCase):
    # Reuse the real folder fixture, without inheriting/re-running its tests.
    setUp = repairs.RepairTests.setUp
    team = repairs.RepairTests.team
    fix = repairs.RepairTests.fix

    def test_stop_after_first_vote_prevents_mutation(self):
        team, models = self.team([self.fix(), repairs.action('finish')])
        team.cancelled = lambda: any(phase == 'review' for _,phase,_ in models.calls)
        result = team.run()
        self.assertEqual(result['status'], 'interrupted')
        self.assertIn('a - b', (self.workspace.root/'calc.py').read_text())
        self.assertEqual(len([c for c in models.calls if c[1] == 'review']), 1)
        self.assertEqual(json.loads((self.run_dir/'result.json').read_text())['status'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
