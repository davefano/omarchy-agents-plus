"""Exercise UI name persistence with fake accounts and the installed shell API."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parent
SHELL = Path('/usr/share/omarchy/shell')


@unittest.skipUnless(shutil.which('qs') and SHELL.is_dir() and os.environ.get('WAYLAND_DISPLAY'),
                     'Requires the installed Omarchy UI and a Wayland session')
class AccountSettingsTests(unittest.TestCase):
    def test_saved_names_survive_stale_settings_and_later_edits(self):
        with tempfile.TemporaryDirectory(prefix='agents-settings-test-') as temporary:
            root = Path(temporary)
            for name in ('Panel.qml', 'Main.qml', 'Agent.qml', 'AddAccountDialog.qml',
                         'EditAccountDialog.qml', 'OverviewSettingsDialog.qml', 'reset_times.py'):
                shutil.copy(REPO / name, root / name)
            # Keep the real panel logic, but never map a popup or steal focus.
            panel = root / 'Panel.qml'
            panel.write_text(panel.read_text().replace('open: root.opened', 'open: false'))
            (root / 'refresh_usage.py').write_text('pass\n')
            for name in ('Commons', 'Ui'):
                (root / name).symlink_to(SHELL / name)
            (root / 'assets').symlink_to(REPO / 'assets')
            usage = root / 'state/omarchy/agents/usage'
            usage.mkdir(parents=True)
            for provider in ('claude', 'codex', 'grok'):
                (usage / (provider + '.json')).write_text(json.dumps({
                    'id': provider, 'name': provider.title(), 'ready': True,
                    'limits': [{'label': 'Weekly (7-day)', 'percent': 0.3}] + ([
                        {'label': 'Fable Weekly', 'percent': 0.8},
                        {'label': 'Session (5-hour)', 'percent': 0.1},
                    ] if provider == 'claude' else []),
                }))
            (usage / 'claude-work.json').write_text(json.dumps({
                'id': 'claude-work', 'name': 'Second Claude', 'ready': True,
                'limits': [{'label': 'Weekly (7-day)', 'percent': 0.5},
                           {'label': 'Fable Weekly', 'percent': 0.2}],
            }))

            # Use the actual whole-entry update API, not a mock that silently
            # merges names and hides stale settings overwrites.
            stock = (SHELL / 'shell.qml').read_text()
            start = stock.index('  function updateEntryInline(')
            end = stock.index('\n  // ----', start)
            method = stock[start:end].replace('    var stripped =',
                '    if (test.failWrite) return false\n    var stripped =', 1)
            fixture = (REPO / 'tests/account_settings.qml').read_text()
            (root / 'shell.qml').write_text(fixture.replace('// UPDATE_ENTRY_INLINE', method))
            env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'),
                       XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'))
            result = subprocess.run(['qs', '-p', str(root), '--no-color'], env=env,
                                    capture_output=True, text=True, timeout=12)
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertIn('ACCOUNT_SETTINGS_REGRESSION_PASSED', output)
            self.assertNotIn('FAILED:', output)
            saved = json.loads((root / 'saved-shell.json').read_text())
            entry = saved['bar']['layout']['right'][0]
            self.assertEqual(entry['providers']['claude']['name'], 'Updated personal')
            self.assertEqual(entry['providers']['codex']['name'], 'Work')
            self.assertFalse(entry['providers']['codex-disabled']['enabled'])
            self.assertEqual(entry['refreshIntervalSec'], 123)
            self.assertEqual(entry['overviewMetrics']['anthropic'], 'fable weekly')
            self.assertEqual(entry['overviewSorts']['anthropic'], 'usage-asc')


if __name__ == '__main__':
    unittest.main()
