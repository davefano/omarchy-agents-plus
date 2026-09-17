#!/usr/bin/env python3
"""Publish extra Codex logins to My Agents; never replace the default record."""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from refresh_usage import wanted

MANAGED_BY = 'davidfano.codex-accounts'


def accounts():
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'omarchy/agents/codex-accounts.json'
    if config.exists():
        rows = json.loads(config.read_text())['accounts']
        if not isinstance(rows, list):
            raise ValueError('accounts must be an array')
    else:
        rows = [{'id': p.name.removeprefix('.codex-'), 'configDir': str(p)}
                for p in sorted(home.glob('.codex-*')) if (p / 'auth.json').is_file()]
    default = Path(os.environ.get('CODEX_HOME') or home / '.codex').resolve()
    result, ids, dirs = [], set(), {default}
    for row in rows:
        if row.get('enabled', True) is False:
            continue
        raw = str(row.get('id') or Path(row['configDir']).name.lstrip('.'))
        key = re.sub('[^a-z0-9._-]+', '-', raw.lower()).strip('._-')
        if not key or key == 'codex':
            raise ValueError('extra accounts need a non-default id')
        key = key if key.startswith('codex-') else 'codex-' + key
        directory = Path(row.get('configDir') or home / ('.' + key)).expanduser().resolve()
        if directory == default:
            continue
        if key in ids or directory in dirs:
            raise ValueError('duplicate Codex account id or directory')
        ids.add(key)
        dirs.add(directory)
        result.append({'id': key, 'name': row.get('name') or 'Codex · ' + key[6:], 'configDir': str(directory)})
    return result


def collect_native():
    # Use the installed parser and official app-server RPC, but omit shared
    # pi/OpenCode history: those logs cannot be attributed to this saved login.
    source = Path(os.environ.get('OMARCHY_PATH') or '/usr/share/omarchy') / 'bin/omarchy-agent-usage-codex'
    loader = importlib.machinery.SourceFileLoader('codex_collector', str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    collector = importlib.util.module_from_spec(spec)
    loader.exec_module(collector)
    collector.scan_pi_sessions = lambda: None
    collector.scan_opencode_sessions = lambda: True
    collector.main()


def publish(account, flags, usage, cache):
    directory = Path(account['configDir'])
    if not directory.is_dir():
        raise ValueError(f"{directory} does not exist")
    env = os.environ.copy()
    env['CODEX_HOME'] = str(directory)
    env['XDG_CACHE_HOME'] = str(cache / account['id'])
    for key in ('OPENAI_API_KEY', 'OPENAI_ACCESS_TOKEN', 'CODEX_ACCESS_TOKEN'):
        env.pop(key, None)
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--collect-native', *flags],
                          env=env, cwd=directory, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=90, check=True)
    record = json.loads(proc.stdout)
    if not isinstance(record, dict) or record.get('id') != 'codex':
        raise ValueError('unexpected Codex collector record')
    record.update(account, managedBy=MANAGED_BY)
    if record.get('authHelpText'):
        record['authHelpText'] = record['authHelpText'].replace(
            '`codex login`', f'`CODEX_HOME={shlex.quote(str(directory))} codex login`')
    usage.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + account['id'], dir=usage)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(record, handle)
            handle.write('\n')
        os.replace(temporary, usage / (account['id'] + '.json'))
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    if '--collect-native' in sys.argv:
        sys.argv.remove('--collect-native')
        collect_native()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--limits-only', action='store_true')
    parser.add_argument('--except', dest='excluded', action='append', default=[])
    parser.add_argument('ids', nargs='*', help='account ids, or list to show saved accounts')
    args = parser.parse_args()
    resolved = accounts()  # Invalid configuration never prunes existing records.
    if args.ids == ['list']:
        print(json.dumps(resolved, indent=2))
        return 0
    home = Path.home()
    usage = Path(os.environ.get('XDG_STATE_HOME') or home / '.local/state') / 'omarchy/agents/usage'
    cache = Path(os.environ.get('XDG_CACHE_HOME') or home / '.cache') / 'omarchy/codex-accounts-native-v1'
    flags = [flag for flag, on in [('--force', args.force), ('--limits-only', args.limits_only)] if on]
    status = 0
    for account in resolved:
        if wanted(account['id'], sys.argv[1:]):
            try:
                publish(account, flags, usage, cache)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                print(f"codex-accounts: {account['id']}: collection failed ({type(exc).__name__}); retaining previous usage", file=sys.stderr)
                status = 1
    configured = {account['id'] for account in resolved}
    for path in usage.glob('codex-*.json'):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get('managedBy') == MANAGED_BY and path.stem not in configured:
            path.unlink()
    return status


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f'codex-accounts: invalid configuration or unavailable collector ({type(exc).__name__})', file=sys.stderr)
        sys.exit(1)
