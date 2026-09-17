import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class InstallTests(unittest.TestCase):
    def test_backup_link_and_idempotent_reinstall(self):
        repo = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            config, state = home / 'config', home / 'state'
            plugin = config / 'omarchy/plugins/davidfano.agents'
            launcher = home / '.local/bin/codex-account'
            plugin.mkdir(parents=True)
            (plugin / 'original').write_text('working plugin')
            launcher.parent.mkdir(parents=True)
            launcher.write_text('working launcher')
            env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(state))
            command = [sys.executable, str(repo / 'scripts/install-local.py')]
            subprocess.run(command, env=env, check=True, capture_output=True)
            self.assertTrue(plugin.is_symlink())
            self.assertEqual(plugin.resolve(), repo)
            self.assertEqual(launcher.resolve(), repo / 'bin/codex-account')
            backups = list((state / 'omarchy/agents/backups').iterdir())
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'davidfano.agents/original').read_text(), 'working plugin')
            self.assertEqual((backups[0] / 'codex-account').read_text(), 'working launcher')
            subprocess.run(command, env=env, check=True, capture_output=True)
            self.assertEqual(list((state / 'omarchy/agents/backups').iterdir()), backups)


if __name__ == '__main__':
    unittest.main()
