"""Repair regressions: real file edits, shell tests, consensus, conflict recovery."""
from collections import deque
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from constrained import grammar_for
from repair_team import RepairTeam, CodingModels, PROPOSAL_SCHEMA
from repair_workspace import FolderWorkspace, WSLWorkspace, file_tool, resolve_file, target_lock
from repair_servers import LazyServers


def proposal(tool, **kwargs):
    return dict(summary='Reparar suma', tool=tool, path='', line='', search='', content='', **kwargs)


def action(tool, **kwargs):
    value = proposal(tool)
    value.update(kwargs)
    return value


class ScriptedModels:
    names = ('Dars', 'Rade', 'Miso')

    def __init__(self, proposals, veto=None):
        self.proposals = deque(proposals)
        self.veto = veto
        self.calls = []

    def ask(self, name, phase, context):
        self.calls.append((name, phase, context))
        if phase == 'propose':
            return self.proposals.popleft()
        decision = 'request_changes' if self.veto == name else 'approve'
        return {'decision': decision, 'reason': 'Falta evidencia.' if decision == 'request_changes' else 'Cambio revisado.'}


class RepairTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.source = self.base/'source'
        self.source.mkdir()
        (self.source/'calc.py').write_text('def add(a, b):\n    return a - b\n', encoding='utf-8')
        (self.source/'test_calc.py').write_text(
            'import unittest\nfrom calc import add\nclass TestAdd(unittest.TestCase):\n'
            '    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n', encoding='utf-8')
        self.run_dir = self.base/'run'
        self.run_dir.mkdir()
        self.workspace = FolderWorkspace(self.source, self.run_dir)

    def team(self, proposals, veto=None, steps=None, workspace=None):
        models = ScriptedModels(proposals, veto)
        team = RepairTeam(workspace or self.workspace, models, 'Corregir la suma',
                          'python -m unittest -q', self.run_dir,
                          max_steps=steps or len(proposals), emit=lambda value: None)
        return team, models

    def fix(self):
        return action('replace', path='calc.py', search='return a - b', content='return a + b')

    def test_real_edit_verify_and_publish_with_backup(self):
        team, models = self.team([self.fix(), action('finish')])
        result = team.run()
        self.assertEqual(result['status'], 'verified')
        self.assertIn('a - b', (self.source/'calc.py').read_text())
        self.assertEqual(result['last_test']['exit_code'], 0)
        self.assertEqual(len([c for c in models.calls if c[1] == 'review']), 6)
        self.workspace.publish(result['approved_fingerprint'])
        self.assertIn('a + b', (self.source/'calc.py').read_text())
        self.assertIn('a - b', (self.run_dir/'backups'/'calc.py').read_text())
        self.assertIn('-    return a - b', (self.run_dir/'changes.diff').read_text())
        events = [json.loads(line) for line in (self.run_dir/'discussion.jsonl').read_text().splitlines()]
        self.assertEqual([e['exit_code'] for e in events if e['kind'] == 'test_result'], [1, 0, 0])

    def test_one_veto_prevents_any_mutation(self):
        team, models = self.team([self.fix()], veto='Miso')
        result = team.run()
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('a - b', (self.workspace.root/'calc.py').read_text())
        self.assertEqual([c[0] for c in models.calls if c[1] == 'review'], list(models.names))

    def test_bad_fragment_rejected_before_requesting_votes(self):
        team, models = self.team([action('replace', path='calc.py', search='imaginary code', content='x')])
        result = team.run()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual([c for c in models.calls if c[1] == 'review'], [])
        self.assertIn('a - b', (self.workspace.root/'calc.py').read_text())

    def test_target_lock_excludes_second_repair_and_releases(self):
        with target_lock(self.base/'locks', 'same target'):
            with self.assertRaises(ValueError):
                with target_lock(self.base/'locks', 'same target'):
                    self.fail('second writer acquired lock')
        with target_lock(self.base/'locks', 'same target'):
            pass

    def test_failed_verification_never_requests_finish_votes(self):
        team, models = self.team([action('finish')])
        result = team.run()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual([c for c in models.calls if c[1] == 'review'], [])

    def test_finish_veto_prevents_verified_status(self):
        self.workspace.tool(self.fix())
        team, models = self.team([action('finish')], veto='Rade')
        self.assertEqual(team.run()['status'], 'incomplete')

    def test_reviewers_receive_identical_proposal_and_evidence(self):
        team, models = self.team([self.fix()])
        team.run()
        contexts = [c[2] for c in models.calls if c[1] == 'review']
        self.assertEqual(len(set(contexts)), 1)
        self.assertIn('Corregir la suma', contexts[0])
        self.assertIn('return a + b', contexts[0])

    def test_source_conflict_checked_before_any_publish(self):
        self.workspace.tool(self.fix())
        self.workspace.tool(action('write', path='new.py', content='x=1\n'))
        (self.source/'calc.py').write_text('cambio del usuario', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Conflicto'):
            self.workspace.publish(self.workspace.changes()['fingerprint'])
        self.assertFalse((self.source/'new.py').exists())
        self.assertEqual((self.source/'calc.py').read_text(), 'cambio del usuario')

    def test_publish_refuses_workspace_changed_since_review(self):
        fingerprint = self.workspace.changes()['fingerprint']
        self.workspace.tool(self.fix())
        with self.assertRaisesRegex(ValueError, 'después del consenso'):
            self.workspace.publish(fingerprint)

    def test_publish_rolls_back_files_on_copy_failure(self):
        self.workspace.tool(self.fix())
        self.workspace.tool(action('write', path='zzz.py', content='x=1\n'))
        from repair_workspace import shutil
        real_copy = shutil.copy2

        def fail_later(src, dst, *args, **kwargs):
            if Path(src).name == 'zzz.py':
                raise OSError('simulated disk failure')
            return real_copy(src, dst, *args, **kwargs)

        with patch('repair_workspace.shutil.copy2', side_effect=fail_later):
            with self.assertRaises(OSError):
                self.workspace.publish(self.workspace.changes()['fingerprint'])
        self.assertIn('a - b', (self.source/'calc.py').read_text())
        self.assertFalse((self.source/'zzz.py').exists())

    def test_tools_refuse_escape_git_and_ambiguous_replacement(self):
        for name in ('../outside.txt', '/etc/passwd', '.git/config', 'C:/Windows/x', 'file:stream'):
            if os.name != 'nt' and ':' in name:
                continue
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve_file(self.workspace.root, name)
        with self.assertRaisesRegex(ValueError, 'exacto'):
            self.workspace.tool(action('replace', path='calc.py', search='missing', content='new'))

    def test_search_accepts_a_single_file(self):
        found = self.workspace.tool(action('search', path='calc.py', search='return'))
        self.assertIn('calc.py:2:', found)
        self.assertIn('a - b', found)

    def test_wsl_domain_error_remains_recoverable(self):
        workspace = object.__new__(WSLWorkspace)
        workspace.root = '/workspace'
        with patch.object(workspace, '_python', return_value=json.dumps({'ok':False,'error':'Archivo inexistente'})):
            with self.assertRaisesRegex(ValueError, 'inexistente'):
                workspace.tool(action('read', path='missing.py'))

    def test_junction_cannot_escape_or_be_copied(self):
        outside = self.base/'outside'
        outside.mkdir()
        (outside/'private.txt').write_text('outside')
        link = self.workspace.root/'linked'
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                           capture_output=True, check=True)
            self.addCleanup(lambda: os.rmdir(link))
        else:
            link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.workspace.tool(action('read', path='linked/private.txt'))
        self.assertNotIn('private.txt', self.workspace.tool(action('list')))

    def test_timeout_records_failure_and_keeps_full_log(self):
        result = self.workspace.command('python -c "import time; print(123, flush=True); time.sleep(10)"',
                                        1, self.run_dir/'timeout.log')
        self.assertTrue(result['timeout'])
        self.assertEqual(result['exit_code'], 124)
        self.assertIn('123', result['output'])

    def test_command_nonzero_is_not_treated_as_success(self):
        result = self.workspace.command('python -c "raise SystemExit(7)"', 10, self.run_dir/'fail.log')
        self.assertNotEqual(result['exit_code'], 0)

    def test_no_roleplay_prompts_or_vault_in_coding_transport(self):
        cfg = {'agents': {n: {'url':'http://127.0.0.1:1234'} for n in ('Dars','Rade','Miso')},
               'model_compat': {'Miso':'gemma2'}}
        models = CodingModels(cfg)
        value = action('read', path='calc.py')
        with patch('repair_team.request', return_value={'choices':[{'message': {'content':json.dumps(value)}}]}) as transport:
            models.ask('Miso', 'propose', 'OBJETIVO COMPARTIDO')
        payload = transport.call_args.args[1]
        self.assertEqual([m['role'] for m in payload['messages']], ['user'])
        self.assertIn('OBJETIVO COMPARTIDO', payload['messages'][0]['content'])
        self.assertNotIn('DarsVault', payload['messages'][0]['content'])
        self.assertIn('grammar', payload)

    def test_grammar_allows_code_larger_than_narrative_limit(self):
        grammar = grammar_for(PROPOSAL_SCHEMA)
        self.assertIn('char{0,10000}', grammar)
        with self.assertRaises(ValueError):
            grammar_for({'type':'string','maxLength':50000})

    def test_unmanaged_wsl_cannot_receive_root_tools(self):
        for distro in ('Debian', 'DarsVault', 'docker-desktop', 'AgentLab-x --exec evil'):
            with self.subTest(distro=distro), self.assertRaises(ValueError):
                WSLWorkspace(distro)

    def test_lazy_loading_stops_only_previously_owned_model(self):
        cfg = {'agents': {n:{'url':f'http://127.0.0.1:{p}'} for n,p in (('Dars',8081),('Rade',8082),('Miso',8083))}}
        with patch('repair_servers.BASE', self.base), patch('repair_servers.shutil.which', return_value='pwsh'), patch.object(LazyServers, '_invoke') as invoke:
            manager = LazyServers(cfg)
            manager.ensure('Dars')
            manager.ensure('Dars')
            manager.ensure('Rade')
            manager.close()
        from unittest.mock import call
        self.assertEqual(invoke.call_args_list, [call('Dars'),call('Dars',stop=True),call('Rade'),call('Rade',stop=True)])

    def test_model_failure_persists_incomplete_work(self):
        team, models = self.team([self.fix(), action('finish')])
        original_ask = models.ask

        def broken(name, phase, context):
            if phase == 'propose' and not models.proposals:
                raise RuntimeError('offline')
            return original_ask(name, phase, context)

        models.proposals.pop()
        models.ask = broken
        result = team.run()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('a + b', (self.workspace.root/'calc.py').read_text())
        self.assertIn('a - b', (self.source/'calc.py').read_text())
        self.assertEqual(json.loads((self.run_dir/'result.json').read_text())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
