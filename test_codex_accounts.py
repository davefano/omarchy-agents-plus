import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import codex_accounts as accounts


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        env = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / 'config'),
               'XDG_STATE_HOME': str(self.home / 'state'), 'XDG_CACHE_HOME': str(self.home / 'cache')}
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.codex_home = patch.dict(os.environ, CODEX_HOME=str(self.home / '.codex'))
        self.codex_home.start()
        self.addCleanup(self.codex_home.stop)

    def config(self, rows):
        path = self.home / 'config/omarchy/agents/codex-accounts.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'accounts': rows}))

    def test_discovery_and_default_alias(self):
        work = self.home / '.codex-work'
        work.mkdir()
        (work / 'auth.json').write_text('{}')
        default = self.home / '.codex'
        default.mkdir()
        (default / 'auth.json').write_text('{}')
        (self.home / '.codex-alias').symlink_to(default)
        self.assertEqual([a['id'] for a in accounts.accounts()], ['codex-work'])
        self.config([])
        self.assertEqual(accounts.accounts(), [])

    def test_duplicate_and_reserved_ids(self):
        self.config([{'id': 'codex', 'configDir': str(self.home / 'work')}])
        with self.assertRaises(ValueError):
            accounts.accounts()
        self.config([{'id': 'work'}, {'id': 'codex-work'}])
        with self.assertRaises(ValueError):
            accounts.accounts()

    def test_isolated_publish_and_failure_preserves_record(self):
        directory = self.home / 'work space'
        directory.mkdir()
        account = {'id': 'codex-work', 'name': 'Work', 'configDir': str(directory)}
        usage, cache = self.home / 'usage', self.home / 'cache'
        record = {'id': 'codex', 'authHelpText': 'Run `codex login` to authenticate.'}
        result = subprocess.CompletedProcess([], 0, json.dumps(record), '')
        with patch.dict(os.environ, OPENAI_API_KEY='test'), patch.object(accounts.subprocess, 'run', return_value=result) as run:
            accounts.publish(account, ['--limits-only'], usage, cache)
            env = run.call_args.kwargs['env']
            self.assertEqual(env['CODEX_HOME'], str(directory))
            self.assertEqual(env['XDG_CACHE_HOME'], str(cache / 'codex-work'))
            self.assertNotIn('OPENAI_API_KEY', env)
        path = usage / 'codex-work.json'
        saved = path.read_text()
        self.assertIn("CODEX_HOME='", json.loads(saved)['authHelpText'])
        with patch.object(accounts.subprocess, 'run', side_effect=subprocess.TimeoutExpired('test', 90)):
            with self.assertRaises(subprocess.TimeoutExpired):
                accounts.publish(account, [], usage, cache)
        self.assertEqual(path.read_text(), saved)

    def test_prunes_only_owned_records(self):
        usage = self.home / 'state/omarchy/agents/usage'
        usage.mkdir(parents=True)
        (usage / 'codex-old.json').write_text(json.dumps({'managedBy': accounts.MANAGED_BY}))
        (usage / 'codex-other.json').write_text('{}')
        (usage / 'codex.json').write_text('{}')
        self.config([])
        with patch('sys.argv', ['codex_accounts.py']):
            self.assertEqual(accounts.main(), 0)
        self.assertFalse((usage / 'codex-old.json').exists())
        self.assertTrue((usage / 'codex-other.json').exists())
        self.assertTrue((usage / 'codex.json').exists())


if __name__ == '__main__':
    unittest.main()
