import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import add_account


class AddAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.home / 'config')}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def config(self, provider='openai'):
        return add_account.config_path(add_account.PROVIDERS[provider])

    def test_success_preserves_discovered_accounts_and_display_name(self):
        old = self.home / '.codex-personal'
        old.mkdir()
        (old / 'auth.json').write_text('{}')
        def login(command, **kwargs):
            directory = Path(kwargs['env']['CODEX_HOME'])
            self.assertNotEqual(directory, self.home / '.codex')
            (directory / 'auth.json').write_text('{}')
            return type('Result', (), {'returncode': 0})()
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.run', side_effect=login), \
             patch('add_account.refresh') as refresh:
            add_account.authenticate('openai', 'Client Work')
        data = json.loads(self.config().read_text())
        self.assertEqual([row['id'] for row in data['accounts']], ['codex-personal', 'codex-client-work'])
        self.assertEqual(data['accounts'][1]['name'], 'Client Work')
        refresh.assert_called_once()

    def test_failure_does_not_register_account(self):
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.run', return_value=type('Result', (), {'returncode': 1})()), \
             self.assertRaises(ValueError):
            add_account.authenticate('openai', 'Work')
        self.assertFalse(self.config().exists())

    def test_failed_login_with_credentials_does_not_become_discoverable(self):
        def failed_login(command, **kwargs):
            (Path(kwargs['env']['CODEX_HOME']) / 'auth.json').write_text('{}')
            return subprocess.CompletedProcess(command, 1)
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.run', side_effect=failed_login), \
             self.assertRaises(ValueError):
            add_account.authenticate('openai', 'Work')
        self.assertEqual(add_account.codex_accounts.accounts(), [])
        self.assertFalse((self.home / '.codex-work').exists())
        add_account.prepare('openai', 'Work', check_dependencies=False)

    def test_discovered_display_name_cannot_be_duplicated(self):
        directory = self.home / '.codex-work'
        directory.mkdir()
        (directory / 'auth.json').write_text('{}')
        with self.assertRaises(ValueError):
            add_account.prepare('openai', 'Codex · work', check_dependencies=False)

    def test_disabled_account_and_settings_are_preserved(self):
        path = self.config()
        path.parent.mkdir(parents=True)
        original = {'refreshIntervalSec': 123, 'accounts': [
            {'id': 'work', 'name': 'Work', 'enabled': False}]}
        path.write_text(json.dumps(original))
        with self.assertRaises(ValueError):
            add_account.prepare('openai', 'Work', check_dependencies=False)
        self.assertEqual(json.loads(path.read_text()), original)

    def test_invalid_names_and_unknown_provider(self):
        for name in ('', '  ', '../', 'x\ny', 'x' * 81):
            with self.subTest(name=name), self.assertRaises(ValueError):
                add_account.prepare('openai', name, check_dependencies=False)
        with self.assertRaises(ValueError):
            add_account.prepare('unknown', 'Work', check_dependencies=False)

    def test_existing_credentials_and_symlinks_are_rejected(self):
        directory = self.home / '.codex-work'
        directory.symlink_to(self.home / '.codex')
        with self.assertRaises(ValueError):
            add_account.prepare('openai', 'Work', check_dependencies=False)

    def test_malformed_config_is_not_replaced(self):
        path = self.config()
        path.parent.mkdir(parents=True)
        path.write_text('{broken')
        with self.assertRaises(ValueError):
            add_account.prepare('openai', 'Work', check_dependencies=False)
        self.assertEqual(path.read_text(), '{broken')

    def test_commands_isolate_auth_and_pass_arguments_without_shell(self):
        for provider, variable, expected in [
            ('openai', 'CODEX_HOME', ['codex', '-c', 'cli_auth_credentials_store="file"', 'login']),
            ('anthropic', 'CLAUDE_CONFIG_DIR', ['claude', 'auth', 'login']),
            ('xai', 'GROK_HOME', ['grok', 'login'])]:
            with self.subTest(provider=provider):
                plan = add_account.prepare(provider, "Work's $(echo test)", check_dependencies=False)
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake', 'ANTHROPIC_API_KEY': 'fake',
                                            'XAI_API_KEY': 'fake', 'GROK_AUTH_PROVIDER_COMMAND': 'fake'}):
                    command, env = add_account.login_command(plan)
                self.assertEqual(command, expected)
                self.assertEqual(env[variable], str(plan['directory']))
                self.assertNotIn('OPENAI_API_KEY', env)
                self.assertNotIn('ANTHROPIC_API_KEY', env)
                self.assertNotIn('XAI_API_KEY', env)
                self.assertNotIn('GROK_AUTH_PROVIDER_COMMAND', env)

    def executable(self, path, source):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!' + sys.executable + '\n' + source)
        path.chmod(0o700)

    def test_terminal_login_registration_and_collection_with_fake_clis(self):
        """Exercise the process boundary without live credentials or providers."""
        binary = self.home / 'bin'
        self.executable(binary / 'xdg-terminal-exec',
            'import subprocess, sys\nsys.exit(subprocess.call(sys.argv[2:]))\n')
        for cli, variable, credential in [('codex', 'CODEX_HOME', 'auth.json'),
                                           ('claude', 'CLAUDE_CONFIG_DIR', '.credentials.json'),
                                           ('grok', 'GROK_HOME', 'auth.json')]:
            self.executable(binary / cli,
                'import os\nfrom pathlib import Path\n'
                f"(Path(os.environ[{variable!r}]) / {credential!r}).write_text('{{}}')\n")
        collector = self.home / 'omarchy/bin/omarchy-agent-usage-codex'
        self.executable(collector, 'def main():\n    print(\'{"id":"codex","ready":true}\')\n')
        self.executable(add_account.claude_helper(),
            'import sys\n'
            'if sys.argv[1:] == ["list"]: print("[]")\n')
        (add_account.config_home() / 'omarchy/plugins/davidfano.agents').symlink_to(Path(add_account.__file__).parent)
        env = {'PATH': str(binary) + os.pathsep + os.defpath,
               'OMARCHY_PATH': str(self.home / 'omarchy'),
               'XDG_STATE_HOME': str(self.home / 'state'),
               'XDG_CACHE_HOME': str(self.home / 'cache')}
        with patch.dict(os.environ, env):
            for provider in ('openai', 'anthropic', 'xai'):
                with self.subTest(provider=provider):
                    result = subprocess.run([sys.executable, str(Path(add_account.__file__)),
                                             'launch', '--', provider, "- Work's Team"],
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    deadline = time.monotonic() + 5
                    while not self.config(provider).exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    data = json.loads(self.config(provider).read_text())
                    self.assertEqual(data['accounts'][-1]['name'], "- Work's Team")
                    account = data['accounts'][-1]
                    credential = Path(account['configDir']) / add_account.PROVIDERS[provider]['credentials']
                    credential.write_text('old fake login')
                    result = subprocess.run([sys.executable, str(Path(add_account.__file__)),
                        'launch-reauth', '--', provider, account['name'], account['id'], account['configDir']],
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    deadline = time.monotonic() + 5
                    while credential.read_text() != '{}' and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertEqual(credential.read_text(), '{}')
                    self.assertEqual(json.loads(self.config(provider).read_text()), data)
            record = self.home / 'state/omarchy/agents/usage/codex-work-s-team.json'
            self.assertEqual(json.loads(record.read_text())['id'], 'codex-work-s-team')
            result = subprocess.run([sys.executable, str(Path(add_account.__file__).parent / 'bin/codex-account'),
                                     'later', 'login'], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(self.config().read_text())
            self.assertEqual(data['accounts'][-1]['id'], 'codex-later')
            self.assertEqual(data['accounts'][0]['name'], "- Work's Team")
            self.assertTrue((record.parent / 'codex-later.json').exists())
        self.assertFalse((self.home / '.codex').exists())
        self.assertFalse((self.home / '.claude').exists())
        self.assertFalse((self.home / '.grok').exists())

    def test_missing_claude_adapter_fails_before_login(self):
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             self.assertRaisesRegex(ValueError, 'Claude Accounts plugin'):
            add_account.prepare('anthropic', 'Work')

    def test_configured_default_directory_is_never_used(self):
        with patch.dict(os.environ, CODEX_HOME=str(self.home / '.codex-work')), \
             self.assertRaises(ValueError):
            add_account.prepare('openai', 'Work', check_dependencies=False)

    def test_long_running_terminal_is_not_killed(self):
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.Popen') as popen:
            popen.return_value.wait.side_effect = subprocess.TimeoutExpired('terminal', 0.5)
            add_account.launch('openai', "Work's Team")
            command = popen.call_args.args[0]
            self.assertEqual(command[-2:], ['openai', "Work's Team"])
            self.assertNotIn('shell', popen.call_args.kwargs)
            popen.return_value.kill.assert_not_called()
            popen.return_value.terminate.assert_not_called()

    def test_success_preserves_explicit_settings_and_disabled_accounts(self):
        path = self.config()
        path.parent.mkdir(parents=True)
        disabled = {'id': 'old', 'name': 'Old', 'enabled': False, 'custom': True}
        path.write_text(json.dumps({'accounts': [disabled], 'refreshIntervalSec': 123}))
        def login(command, **kwargs):
            (Path(kwargs['env']['CODEX_HOME']) / 'auth.json').write_text('{}')
            return subprocess.CompletedProcess(command, 0)
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.run', side_effect=login), \
             patch('add_account.refresh'):
            add_account.authenticate('openai', 'New')
        data = json.loads(path.read_text())
        self.assertEqual(data['refreshIntervalSec'], 123)
        self.assertEqual(data['accounts'][0], disabled)

    def test_concurrent_login_is_rejected_before_provider_runs(self):
        path = self.config().parent / 'add-account.lock'
        path.parent.mkdir(parents=True)
        with path.open('a') as lock, patch('add_account.subprocess.run') as run:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'in progress'):
                add_account.authenticate('openai', 'Work')
            run.assert_not_called()

    def test_settings_edited_during_login_are_preserved(self):
        edited = {'accounts': [], 'refreshIntervalSec': 123}
        def login(command, **kwargs):
            (Path(kwargs['env']['CODEX_HOME']) / 'auth.json').write_text('{}')
            self.config().write_text(json.dumps(edited))
            return subprocess.CompletedProcess(command, 0)
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.run', side_effect=login), \
             patch('add_account.refresh') as refresh, \
             self.assertRaisesRegex(ValueError, 'settings changed'):
            add_account.authenticate('openai', 'Work')
        self.assertEqual(json.loads(self.config().read_text()), edited)
        self.assertTrue((self.home / '.codex-work/auth.json').exists())
        refresh.assert_not_called()

    def test_cli_registration_keeps_disabled_accounts_and_custom_names(self):
        path = self.config()
        path.parent.mkdir(parents=True)
        original = {'accounts': [{'id': 'work', 'name': 'Custom', 'enabled': False}], 'setting': 42}
        path.write_text(json.dumps(original))
        add_account.register_codex_login('work')
        self.assertEqual(json.loads(path.read_text()), original)

    def test_reauthentication_uses_existing_folder_without_registering_or_touching_other_accounts(self):
        for provider_id, provider in add_account.PROVIDERS.items():
            with self.subTest(provider=provider_id):
                directory = self.home / (provider_id + ' custom folder')
                directory.mkdir()
                credential = directory / provider['credentials']
                credential.write_text('old fake login')
                (directory / 'settings.json').write_text('keep settings')
                default = self.home / ('.' + provider['family'])
                default.mkdir()
                (default / provider['credentials']).write_text('other fake login')
                path = self.config(provider_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                original = {'accounts': [{'id': provider['family'] + '-work',
                    'name': 'Custom name', 'configDir': str(directory)}], 'setting': 123}
                path.write_text(json.dumps(original))

                def login(command, **kwargs):
                    self.assertEqual(command, provider['login'])
                    self.assertEqual(kwargs['cwd'], directory)
                    self.assertEqual(kwargs['env'][provider['env']], str(directory))
                    self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
                    self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', kwargs['env'])
                    credential.write_text('new fake login')
                    return subprocess.CompletedProcess(command, 0)

                with patch('add_account.shutil.which', return_value='/bin/fake'), \
                     patch.dict(os.environ, OPENAI_API_KEY='fake', CLAUDE_CODE_OAUTH_TOKEN='fake'), \
                     patch('add_account.subprocess.run', side_effect=login), \
                     patch('add_account.refresh') as refresh:
                    plan = add_account.reauthenticate(provider_id, 'Custom name',
                        provider['family'] + '-work', str(directory))
                self.assertEqual(plan['name'], 'Custom name')
                refresh.assert_called_once_with(plan)
                self.assertEqual(credential.read_text(), 'new fake login')
                self.assertEqual((default / provider['credentials']).read_text(), 'other fake login')
                self.assertEqual((directory / 'settings.json').read_text(), 'keep settings')
                self.assertEqual(json.loads(path.read_text()), original)

    def test_default_reauthentication_honors_cli_home_and_does_not_create_account_config(self):
        for provider_id, provider in add_account.PROVIDERS.items():
            with self.subTest(provider=provider_id):
                directory = self.home / (provider_id + '-default')
                directory.mkdir()
                def login(command, **kwargs):
                    self.assertEqual(kwargs['env'][provider['env']], str(directory))
                    (directory / provider['credentials']).write_text('{}')
                    return subprocess.CompletedProcess(command, 0)
                with patch.dict(os.environ, {provider['env']: str(directory)}), \
                     patch('add_account.shutil.which', return_value='/bin/fake'), \
                     patch('add_account.subprocess.run', side_effect=login), \
                     patch('add_account.refresh') as refresh:
                    add_account.reauthenticate(provider_id, 'Default', provider['family'], '/ignored/stale/path')
                self.assertFalse(self.config(provider_id).exists())
                self.assertEqual(refresh.call_args.args[0]['id'], provider['family'])

    def test_reauthentication_rejects_unknown_missing_and_mismatched_targets(self):
        default = self.home / '.codex'
        default.mkdir()
        for provider_id, account_id, directory in [
            ('unknown', 'codex-work', str(default)), ('openai', None, str(default)),
            ('openai', 'claude-work', str(default)), ('openai', 'codex-remote', ''),
            ('openai', 'codex-missing', str(self.home / 'missing')),
            ('openai', 'codex-alias', str(default)),
        ]:
            with self.subTest(account=account_id), patch('add_account.subprocess.Popen') as terminal, \
                 self.assertRaises(ValueError):
                add_account.launch_reauthentication(provider_id, 'Work', account_id, directory)
            terminal.assert_not_called()

    def test_failed_reauthentication_does_not_refresh_or_rewrite_account_config(self):
        directory = self.home / '.codex-work'
        directory.mkdir()
        credential = directory / 'auth.json'
        credential.write_text('existing fake login')
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.run', return_value=subprocess.CompletedProcess([], 1)), \
             patch('add_account.refresh') as refresh, self.assertRaisesRegex(ValueError, 'did not complete'):
            add_account.reauthenticate('openai', 'Work', 'codex-work', str(directory))
        refresh.assert_not_called()
        self.assertEqual(credential.read_text(), 'existing fake login')
        self.assertFalse(self.config().exists())

    def test_reauthentication_terminal_passes_exact_target_as_arguments(self):
        directory = self.home / "folder with ' quotes $(literal)"
        directory.mkdir()
        with patch('add_account.shutil.which', return_value='/bin/fake'), \
             patch('add_account.subprocess.Popen') as terminal:
            terminal.return_value.wait.return_value = 0
            add_account.launch_reauthentication('openai', '- Custom name', 'codex-work', str(directory))
        command = terminal.call_args.args[0]
        self.assertEqual(command[-6:], ['reauthenticate', '--', 'openai', '- Custom name',
                                       'codex-work', str(directory)])
        self.assertNotIn('shell', terminal.call_args.kwargs)

    def test_default_refresh_uses_provider_collector_route(self):
        for provider in add_account.PROVIDERS.values():
            with self.subTest(provider=provider['family']), \
                 patch('add_account.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
                add_account.refresh({'provider': provider, 'id': provider['family']})
            expected = 'grok_accounts.py' if provider['family'] == 'grok' else 'refresh_usage.py'
            self.assertEqual(Path(run.call_args.args[0][1]).name, expected)
            self.assertEqual(run.call_args.args[0][-2:], ['--force', provider['family']])


if __name__ == '__main__':
    unittest.main()
