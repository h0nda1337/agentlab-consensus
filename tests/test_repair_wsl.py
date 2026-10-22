"""Opt-in real dedicated WSL tools; uses a disposable Linux project and mocked votes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from repair_workspace import WSLWorkspace
from repair_team import RepairTeam
from test_repair import ScriptedModels, action


@unittest.skipUnless(os.environ.get('AGENTLAB_WSL_INTEGRATION') == '1', 'Set AGENTLAB_WSL_INTEGRATION=1 for managed WSL tests')
class WSLRepairTests(unittest.TestCase):
    def test_root_edit_command_tests_consensus_and_no_windows_interop(self):
        root = '/workspace/agentlab-test-'+uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as folder:
            workspace = WSLWorkspace(root=root, run_dir=folder)
            self.addCleanup(lambda: workspace._python('import shutil,sys; shutil.rmtree(sys.argv[1])', [root]))
            workspace.tool(action('write', path='calc.py', content='def add(a,b):\n    return a-b\n'))
            workspace.tool(action('write', path='test_calc.py', content='import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n    def test_sum(self): self.assertEqual(add(2,3),5)\n'))
            probe = '/etc/agentlab-test-'+uuid.uuid4().hex
            try:
                workspace.tool(action('write', path=probe, content='root access verified'))
                self.assertIn('root access verified', workspace.tool(action('read', path=probe)))
            finally:
                workspace.tool(action('delete', path=probe))
            self.assertIn('calc.py:2:', workspace.tool(action('search', path='calc.py', search='return')))
            models = ScriptedModels([action('read', path='missing.py'), action('replace', path='calc.py', search='return a-b', content='return a+b'), action('finish')])
            team = RepairTeam(workspace, models, 'Reparar suma en WSL', 'python3 -m unittest -v', folder, max_steps=3, emit=lambda _: None)
            result = team.run()
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(result['last_test']['exit_code'], 0)
            self.assertIn('a+b', workspace.tool(action('read', path='calc.py')))
            flags = workspace._python("import json,os; from pathlib import Path; print(json.dumps({'uid':os.getuid(),'interop':bool(os.environ.get('WSL_INTEROP')),'windows_mounted':any('aname=drvfs' in s or ' drvfs ' in s for s in Path('/proc/mounts').read_text().splitlines())}))")
            self.assertEqual(json.loads(flags), {'uid':0,'interop':False,'windows_mounted':False})
