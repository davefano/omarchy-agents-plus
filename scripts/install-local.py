#!/usr/bin/env python3
"""Link this checkout into Omarchy, backing up previous installations."""
from datetime import datetime
import os
from pathlib import Path
import tempfile


def main():
    repo = Path(__file__).resolve().parent.parent
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    state = Path(os.environ.get('XDG_STATE_HOME') or home / '.local/state')
    links = [
        (repo, config / 'omarchy/plugins/davidfano.agents'),
        (repo / 'bin/codex-account', home / '.local/bin/codex-account'),
    ]
    if not (repo / 'manifest.json').is_file() or not links[1][0].is_file():
        raise SystemExit('Run this installer from a complete omarchy-agents checkout.')
    backup = None
    for source, target in links:
        if target.resolve() == source:
            print(f'Already installed: {target}')
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # Prepare the replacement before moving the live installation.
        with tempfile.TemporaryDirectory(prefix='.agents-link-', dir=target.parent) as staging:
            link = Path(staging) / 'link'
            link.symlink_to(source, target_is_directory=source.is_dir())
            previous = None
            if target.exists() or target.is_symlink():
                if backup is None:
                    backups = state / 'omarchy/agents/backups'
                    backups.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-')
                    backup = Path(tempfile.mkdtemp(prefix='install-' + stamp, dir=backups))
                previous = backup / target.name
                target.rename(previous)
            try:
                os.replace(link, target)
            except OSError:
                if previous is not None:
                    previous.rename(target)
                raise
        print(f'Linked {target} -> {source}')
    if backup:
        print(f'Previous installation saved to {backup}')
    print('Enable My Agents if needed: omarchy plugin enable davidfano.agents')
    print('Reload plugin discovery: omarchy-shell shell rescanPlugins')


if __name__ == '__main__':
    main()
