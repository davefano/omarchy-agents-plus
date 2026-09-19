import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import account_identity as identity


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.home),
            'XDG_CACHE_HOME': str(self.home / 'cache')}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def credentials(self, directory, token):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / '.credentials.json').write_text(json.dumps({'claudeAiOauth': {'accessToken': token}}))

    def profile(self, email):
        return io.BytesIO(json.dumps({'account': {'email': email}}).encode())

    def test_claude_uses_token_profile_instead_of_stale_metadata(self):
        directory = self.home / '.claude'
        self.credentials(directory, 'fake-token')
        (directory / '.claude.json').write_text(json.dumps({'oauthAccount': {'emailAddress': 'wrong@example.test'}}))
        with patch.object(identity.urllib.request, 'urlopen', return_value=self.profile('right@example.test')) as request:
            result = identity.resolve('claude')
        self.assertEqual(result['email'], 'right@example.test')
        self.assertEqual(request.call_args.args[0].get_header('Authorization'), 'Bearer fake-token')
        self.assertNotIn('fake-token', json.dumps(result))

    def test_cache_is_per_directory_and_invalidated_by_login_change(self):
        work, personal = self.home / 'work', self.home / 'personal'
        self.credentials(work, 'fake-work')
        self.credentials(personal, 'fake-personal')
        with patch.object(identity.urllib.request, 'urlopen', side_effect=[
                self.profile('work@example.test'), self.profile('personal@example.test'),
                self.profile('new@example.test')]) as request:
            self.assertEqual(identity.resolve('claude-work', str(work))['email'], 'work@example.test')
            self.assertEqual(identity.resolve('claude-work', str(work))['email'], 'work@example.test')
            self.assertEqual(identity.resolve('claude-personal', str(personal))['email'], 'personal@example.test')
            self.credentials(work, 'fake-new')
            self.assertEqual(identity.resolve('claude-work', str(work))['email'], 'new@example.test')
        self.assertEqual(request.call_count, 3)
        for path in (self.home / 'cache').rglob('*.json'):
            self.assertNotIn('fake-', path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_missing_extra_directory_never_uses_default_login(self):
        self.credentials(self.home / '.claude', 'fake-default')
        with patch.object(identity.urllib.request, 'urlopen') as request:
            self.assertEqual(identity.resolve('claude-work')['email'], '')
        request.assert_not_called()

    def test_network_error_does_not_expose_exception_or_old_identity(self):
        directory = self.home / '.claude'
        self.credentials(directory, 'fake-secret')
        with patch.object(identity.urllib.request, 'urlopen', side_effect=OSError('fake-secret')):
            result = identity.resolve('claude')
        self.assertEqual(result['email'], '')
        self.assertNotIn('fake-secret', json.dumps(result))

    def test_codex_email_comes_from_selected_saved_id_token(self):
        directory = self.home / 'codex-work'
        directory.mkdir()
        payload = base64.urlsafe_b64encode(json.dumps({'email': 'codex@example.test'}).encode()).decode().rstrip('=')
        (directory / 'auth.json').write_text(json.dumps({'tokens': {'id_token': 'header.' + payload + '.signature'}}))
        with patch.object(identity.urllib.request, 'urlopen') as request:
            self.assertEqual(identity.resolve('codex-work', str(directory))['email'], 'codex@example.test')
        request.assert_not_called()

    def test_api_key_login_has_no_email_and_no_network_request(self):
        directory = self.home / '.codex'
        directory.mkdir()
        (directory / 'auth.json').write_text(json.dumps({'OPENAI_API_KEY': 'fake-secret'}))
        with patch.object(identity.urllib.request, 'urlopen') as request:
            result = identity.resolve('codex')
        self.assertEqual(result['email'], '')
        self.assertIn('API key', result['status'])
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
