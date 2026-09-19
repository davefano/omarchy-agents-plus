import json
import io
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import account_identity
import grok_accounts


class GrokAccountsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        env = patch.dict(os.environ, {'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.home / 'config'),
            'XDG_STATE_HOME': str(self.home / 'state')}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.usage = self.home / 'state/omarchy/agents/usage'

    def login(self, directory, email):
        directory.mkdir(parents=True)
        (directory / 'auth.json').write_text(json.dumps({
            'https://auth.example.test::client': {'key': 'fake-secret', 'email': email}}))

    def test_default_and_extra_logins_have_separate_records_without_fabricated_usage(self):
        self.login(self.home / '.grok', 'default@example.test')
        self.login(self.home / '.grok-work', 'work@example.test')
        grok_accounts.main([])
        self.assertEqual({p.stem for p in self.usage.glob('*.json')}, {'grok', 'grok-work'})
        for path in self.usage.glob('*.json'):
            text = path.read_text()
            record = json.loads(text)
            self.assertTrue(record['accountAvailable'])
            self.assertEqual(record['limits'], [])
            self.assertFalse(record['hasLocalStats'])
            self.assertNotIn('fake-secret', text)
            self.assertNotIn('@example.test', text)
            self.assertNotIn('todayTotalTokens', record)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_identity_is_local_and_separated_and_honors_default_home(self):
        default, work = self.home / 'custom-default', self.home / '.grok-work'
        self.login(default, 'default@example.test')
        self.login(work, 'work@example.test')
        with patch.dict(os.environ, GROK_HOME=str(default)), \
             patch('account_identity.urllib.request.urlopen') as network:
            self.assertEqual(account_identity.resolve('grok')['email'], 'default@example.test')
            self.assertEqual(account_identity.resolve('grok-work', str(work))['email'], 'work@example.test')
            self.assertEqual(account_identity.resolve('grok-work')['email'], '')
        network.assert_not_called()

    def test_multiple_distinct_identities_are_not_guessed(self):
        folder = self.home / '.grok'
        self.login(folder, 'one@example.test')
        path = folder / 'auth.json'
        data = json.loads(path.read_text())
        data['other'] = {'key': 'another-fake-secret', 'email': 'two@example.test'}
        path.write_text(json.dumps(data))
        result = account_identity.resolve('grok')
        self.assertEqual(result['email'], '')
        self.assertIn('Multiple', result['status'])
        self.assertNotIn('secret', json.dumps(result))

    def test_explicit_config_preserves_names_and_skips_disabled_and_default_aliases(self):
        self.login(self.home / '.grok', 'default@example.test')
        config = self.home / 'config/omarchy/agents/grok-accounts.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'accounts': [
            {'id': 'work', 'name': 'Team', 'configDir': str(self.home / 'team')},
            {'id': 'disabled', 'enabled': False},
            {'id': 'alias', 'configDir': str(self.home / '.grok')},
        ]}))
        accounts = grok_accounts.accounts()
        self.assertEqual([a['id'] for a in accounts], ['grok-work'])
        self.assertEqual(accounts[0]['name'], 'Team')

    def test_filters_and_pruning_leave_other_collectors_records_untouched(self):
        self.login(self.home / '.grok', 'default@example.test')
        self.login(self.home / '.grok-work', 'work@example.test')
        self.usage.mkdir(parents=True)
        stock = self.usage / 'codex.json'
        stock.write_text('{"id":"codex"}')
        grok_accounts.main(['--except', 'grok', 'grok-work'])
        self.assertFalse((self.usage / 'grok.json').exists())
        self.assertTrue((self.usage / 'grok-work.json').exists())
        (self.home / '.grok-work/auth.json').unlink()
        grok_accounts.main([])
        self.assertFalse((self.usage / 'grok-work.json').exists())
        self.assertEqual(stock.read_text(), '{"id":"codex"}')

    def test_billing_periods_zero_and_legacy_values(self):
        fields = grok_accounts.billing_fields({'config': {
            'currentPeriod': {'type': 'USAGE_PERIOD_TYPE_WEEKLY', 'end': '2026-09-22T00:00:00Z'}}})
        self.assertEqual(fields['limits'], [{'label': 'Weekly', 'percent': 0,
                                            'resetsAt': '2026-09-22T00:00:00Z'}])
        monthly = grok_accounts.billing_fields({'config': {
            'creditUsagePercent': 42.5, 'currentPeriod': {'type': 'USAGE_PERIOD_TYPE_MONTHLY'}}})
        self.assertEqual(monthly['limits'][0]['label'], 'Monthly')
        self.assertEqual(monthly['limits'][0]['percent'], 42.5)
        legacy = grok_accounts.billing_fields({'config': {
            'monthlyLimit': {'val': '2000'}, 'used': {'val': '500'}}})
        self.assertEqual(legacy['limits'][0]['percent'], 25)
        self.assertEqual(grok_accounts.billing_fields({'config': None})['limits'], [])
        with self.assertRaises(ValueError):
            grok_accounts.billing_fields({'config': {'creditUsagePercent': float('nan')}})

    def test_requests_are_cached_and_bound_to_login_and_directory(self):
        folder = self.home / '.grok'
        self.login(folder, 'default@example.test')
        auth_path = folder / 'auth.json'
        auth = json.loads(auth_path.read_text())
        auth[next(iter(auth))]['user_id'] = 'fake-user-id'
        auth_path.write_text(json.dumps(auth))
        response = {'config': {'creditUsagePercent': 23,
                              'currentPeriod': {'type': 'USAGE_PERIOD_TYPE_WEEKLY'}}}
        with patch('grok_accounts.urllib.request.urlopen',
                   side_effect=lambda *a, **kw: io.StringIO(json.dumps(response))) as network:
            grok_accounts.main([])
            first = json.loads((self.usage / 'grok.json').read_text())
            self.assertEqual(first['limits'][0]['percent'], 23)
            self.assertNotIn('fake-secret', json.dumps(first))
            request = network.call_args.args[0]
            self.assertEqual(request.full_url, grok_accounts.BILLING_URL)
            self.assertEqual(request.get_header('Authorization'), 'Bearer fake-secret')
            grok_accounts.main(['--limits-only'])
            self.assertEqual(network.call_count, 1)
            grok_accounts.main(['--force'])
            self.assertEqual(network.call_count, 2)
            # Re-auth invalidates the cache immediately, even without --force.
            auth[next(iter(auth))]['key'] = 'replacement-secret'
            auth_path.write_text(json.dumps(auth))
            grok_accounts.main([])
            self.assertEqual(network.call_count, 3)
            other = self.home / '.grok-work'
            other.mkdir()
            (other / 'auth.json').write_text(json.dumps(auth))
            grok_accounts.collect_billing(other, first)
            self.assertEqual(network.call_count, 4)

    def test_transient_failure_preserves_reading_but_changed_login_and_401_clear_it(self):
        folder = self.home / '.grok'
        folder.mkdir()
        path = folder / 'auth.json'
        auth = {'issuer': {'key': 'fake-secret', 'user_id': 'fake-id'}}
        path.write_text(json.dumps(auth))
        with patch('grok_accounts.urllib.request.urlopen', return_value=io.StringIO(
                '{"config":{"creditUsagePercent":42}}')):
            good = grok_accounts.collect_billing(folder, {})
        with patch('grok_accounts.urllib.request.urlopen', side_effect=OSError('private detail')):
            stale = grok_accounts.collect_billing(folder, good, force=True)
            self.assertEqual(stale['limits'], good['limits'])
            self.assertIn('last successful', stale['usageNote'])
            self.assertNotIn('private detail', json.dumps(stale))
            auth['issuer']['key'] = 'new-secret'
            path.write_text(json.dumps(auth))
            fresh_login = grok_accounts.collect_billing(folder, good)
            self.assertEqual(fresh_login['limits'], [])
        with patch('grok_accounts.urllib.request.urlopen', side_effect=urllib.error.HTTPError(
                grok_accounts.BILLING_URL, 401, 'secret error body', {}, None)):
            expired = grok_accounts.collect_billing(folder, good, force=True)
            self.assertEqual(expired['limits'], [])
            self.assertIn('re-auth', expired['usageNote'])
            self.assertNotIn('secret error body', json.dumps(expired))

    def test_ambiguous_auth_does_not_request_an_arbitrary_accounts_usage(self):
        folder = self.home / '.grok'
        folder.mkdir()
        (folder / 'auth.json').write_text(json.dumps({
            'one': {'key': 'fake-one', 'user_id': 'one'},
            'two': {'key': 'fake-two', 'user_id': 'two'}}))
        with patch('grok_accounts.urllib.request.urlopen') as network:
            result = grok_accounts.collect_billing(folder, {})
        network.assert_not_called()
        self.assertEqual(result['limits'], [])


if __name__ == '__main__':
    unittest.main()
