import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).with_name('refresh_usage.py')
spec = importlib.util.spec_from_file_location('refresh_usage', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'account'
        self.config.mkdir()
        self.cache = Path(self.temp.name) / 'cache'
        self.credentials = self.config / '.credentials.json'

    def credentials_at(self, expires, refresh=True):
        data = {'otherSetting': 'preserve', 'claudeAiOauth': {'accessToken': 'fake-access', 'refreshToken': 'fake-refresh' if refresh else '', 'expiresAt': expires}}
        self.credentials.write_text(json.dumps(data))
        return self.credentials.read_bytes()

    def test_expired_login_is_renewed_by_cli_without_editing_credentials(self):
        before = self.credentials_at(1)
        with patch.object(module.subprocess, 'run') as run:
            def renew(*args, **kwargs):
                self.assertEqual(self.credentials.read_bytes(), before)
                self.assertEqual(args[0][-2:], ['-p', '/usage'])
                self.assertIn('--safe-mode', args[0])
                self.assertEqual(kwargs['env']['CLAUDE_CONFIG_DIR'], str(self.config))
                self.credentials_at((time.time()+3600)*1000)
            run.side_effect = renew
            self.assertTrue(module.renew(self.config, self.cache))
            self.assertEqual(run.call_count, 1)

    def test_fresh_login_needs_no_cli_process(self):
        before = self.credentials_at((time.time()+3600)*1000)
        with patch.object(module.subprocess, 'run') as run:
            self.assertTrue(module.renew(self.config, self.cache))
            run.assert_not_called()
        self.assertEqual(self.credentials.read_bytes(), before)

    def test_failed_refresh_preserves_credentials_and_backs_off(self):
        before = self.credentials_at(1)
        with patch.object(module.subprocess, 'run') as run:
            self.assertFalse(module.renew(self.config, self.cache))
            self.assertFalse(module.renew(self.config, self.cache))
            self.assertEqual(run.call_count, 1)
        self.assertEqual(self.credentials.read_bytes(), before)

    def test_missing_refresh_token_does_not_trigger_browser_login(self):
        before = self.credentials_at(1, refresh=False)
        with patch.object(module.subprocess, 'run') as run:
            self.assertFalse(module.renew(self.config, self.cache))
            run.assert_not_called()
        self.assertEqual(self.credentials.read_bytes(), before)

    def test_account_filters_match_collectors(self):
        self.assertTrue(module.wanted('claude', ['--force']))
        self.assertFalse(module.wanted('claude', ['--except', 'claude']))
        self.assertFalse(module.wanted('claude', ['codex']))
        self.assertTrue(module.wanted('claude-work', ['--limits-only','claude-work']))

if __name__ == '__main__': unittest.main()
