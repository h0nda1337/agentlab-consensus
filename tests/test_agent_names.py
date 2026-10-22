import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_names import display_names, update_names
from repair import main
from repair_team import CodingModels
from test_repair import action


class AgentNameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'config.json'
        self.config = {'agents': {n:{'url':f'http://127.0.0.1:{p}'} for n,p in (('Dars',8081),('Rade',8082),('Miso',8083))},
                       'model_compat':{'Miso':'gemma2'}}
        self.path.write_text(json.dumps(self.config), encoding='utf-8')

    def test_rename_all_preserves_ids_urls_and_compatibility(self):
        original = copy.deepcopy(self.config)
        names = update_names(self.config, {'Dars':'Atlas','Rade':'Iris','Miso':'Nova'}, self.path)
        self.assertEqual(list(names.values()), ['Atlas','Iris','Nova'])
        self.assertEqual(set(self.config['agents']), set(original['agents']))
        self.assertEqual(self.config['model_compat'], original['model_compat'])
        for slot in original['agents']:
            self.assertEqual(self.config['agents'][slot]['url'], original['agents'][slot]['url'])

    def test_duplicate_or_control_names_do_not_change_config(self):
        original = self.path.read_bytes()
        for changes in ({'Dars':'Miso'}, {'Dars':'bad\nname'}, {'Dars':''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                update_names(self.config, changes, self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(display_names(self.config)['Dars'], 'Dars')

    def test_cli_can_rename_using_current_display_name(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--config',str(self.path),'agents','names','Atlas','Iris','Nova']), 0)
            self.assertEqual(main(['--config',str(self.path),'agents','rename','Atlas','Atenea']), 0)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['agents']['Dars']['display_name'], 'Atenea')

    def test_model_receives_custom_name_and_same_endpoint(self):
        update_names(self.config, {'Dars':'Atlas','Rade':'Iris','Miso':'Nova'}, self.path)
        models = CodingModels(self.config)
        with patch('repair_team.request', return_value={'choices':[{'message':{'content':json.dumps(action('read',path='calc.py'))}}]}) as transport:
            models.ask('Miso','propose','Objetivo del proyecto')
        self.assertEqual(transport.call_args.args[0], 'http://127.0.0.1:8083/v1/chat/completions')
        self.assertIn('Tu nombre: Nova', transport.call_args.args[1]['messages'][0]['content'])
        self.assertNotIn('Tu nombre: Miso', transport.call_args.args[1]['messages'][0]['content'])
