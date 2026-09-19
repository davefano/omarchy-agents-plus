#!/usr/bin/env python3
"""Launch provider-owned login flows and register extra accounts for My Agents."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import codex_accounts
import grok_accounts


# The form and terminal flow share this registry. Login commands are argv,
# never shell templates containing user input.
PROVIDERS = {
    'anthropic': {'label': 'Anthropic', 'family': 'claude',
                  'env': 'CLAUDE_CONFIG_DIR', 'credentials': '.credentials.json',
                  'login': ['claude', 'auth', 'login']},
    'openai': {'label': 'OpenAI', 'family': 'codex',
               'env': 'CODEX_HOME', 'credentials': 'auth.json',
               'login': ['codex', '-c', 'cli_auth_credentials_store="file"', 'login']},
    'xai': {'label': 'xAI (Grok)', 'family': 'grok',
            'env': 'GROK_HOME', 'credentials': 'auth.json',
            'login': ['grok', 'login']},
}


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')


def claude_helper():
    return config_home() / 'omarchy/plugins/linting.claude-accounts/bin/claude-accounts'


def config_path(provider):
    if provider['family'] == 'claude' and os.environ.get('CLAUDE_ACCOUNTS_CONFIG'):
        return Path(os.environ['CLAUDE_ACCOUNTS_CONFIG']).expanduser()
    return config_home() / f"omarchy/agents/{provider['family']}-accounts.json"


def read_config(provider):
    path = config_path(provider)
    data = json.loads(path.read_text()) if path.exists() else {'accounts': []}
    if not isinstance(data, dict) or not isinstance(data.get('accounts'), list):
        raise ValueError(f'Fix the accounts array in {path} before adding an account.')
    if not all(isinstance(row, dict) for row in data['accounts']):
        raise ValueError(f'Invalid account entry in {path}.')
    return data


def normalized_id(provider, raw):
    family = provider['family']
    key = re.sub('[^a-z0-9._-]+', '-', str(raw).lower()).strip('._-')
    if family == 'claude':
        key = re.sub('-+', '-', key)
        return (key if key.startswith('claude') else 'claude-' + key)[:64]
    return key if key.startswith(family + '-') else family + '-' + key


def prepare(provider_id, name, check_dependencies=True):
    if provider_id not in PROVIDERS:
        raise ValueError('Choose a supported provider.')
    provider = PROVIDERS[provider_id]
    name = name.strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('Enter an account name of 1–80 characters on one line.')
    slug = re.sub('[^a-z0-9]+', '-', name.lower()).strip('-')[:48].rstrip('-')
    if not slug:
        raise ValueError('Include at least one English letter or number in the name.')
    account_id = provider['family'] + '-' + slug
    directory = Path.home() / ('.' + account_id)
    default = Path(os.environ.get(provider['env']) or Path.home() / ('.' + provider['family'])).expanduser()
    if directory.resolve() == default.resolve():
        raise ValueError('That directory is used by your default login. Choose another name.')
    if directory.is_symlink() or directory.exists():
        raise ValueError('That account directory is already in use. Choose another name.')
    if check_dependencies:
        if not shutil.which(provider['login'][0]):
            raise ValueError(f"Install {provider['login'][0]} before adding this account.")
        if provider_id == 'anthropic' and not claude_helper().is_file():
            raise ValueError('Install the Claude Accounts plugin first (see My Agents README).')
    data = read_config(provider)
    discovered = (discovered_accounts(provider)
                  if provider_id != 'anthropic' or claude_helper().is_file() else [])
    for row in data['accounts'] + discovered:
        raw = row.get('id') or Path(row.get('configDir', '')).name.lstrip('.')
        row_dir = Path(row.get('configDir') or Path.home() / ('.' + normalized_id(provider, raw))).expanduser()
        if (normalized_id(provider, raw) == account_id
                or row_dir.resolve() == directory.resolve()
                or str(row.get('name', '')).casefold() == name.casefold()):
            raise ValueError('That account name is already in use. Choose another name.')
    return {'provider': provider, 'name': name, 'id': account_id, 'directory': directory,
            'discovered': discovered}


def login_command(plan):
    env = os.environ.copy()
    for key in ('OPENAI_API_KEY', 'OPENAI_ACCESS_TOKEN', 'CODEX_ACCESS_TOKEN',
                'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN',
                'CLAUDE_CODE_OAUTH_REFRESH_TOKEN', 'CLAUDE_CODE_OAUTH_SCOPES',
                'XAI_API_KEY', 'GROK_API_KEY', 'GROK_AUTH_PROVIDER_COMMAND',
                'GROK_AUTH_EXPIRED'):
        env.pop(key, None)
    env[plan['provider']['env']] = str(plan['directory'])
    return plan['provider']['login'], env


def discovered_accounts(provider):
    if provider['family'] == 'grok':
        return grok_accounts.accounts()
    if provider['family'] == 'codex':
        return codex_accounts.accounts()
    result = subprocess.run([str(claude_helper()), 'list'], capture_output=True,
                            text=True, check=True, timeout=10)
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('Unable to read existing Claude accounts.')
    return rows


def save_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(data, handle, indent=2)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def refresh(plan):
    if plan['provider']['family'] == 'grok':
        command = [sys.executable, str(Path(__file__).with_name('grok_accounts.py'))]
    elif plan['id'] == plan['provider']['family']:
        command = [sys.executable, str(Path(__file__).with_name('refresh_usage.py'))]
    else:
        command = ([sys.executable, str(Path(__file__).with_name('codex_accounts.py'))]
                   if plan['provider']['family'] == 'codex' else [str(claude_helper())])
    try:
        result = subprocess.run([*command, '--force', plan['id']], timeout=120)
        if result.returncode == 0:
            return
    except (OSError, subprocess.SubprocessError):
        pass
    print('Account saved. Usage could not refresh yet; press R in My Agents to retry.')


@contextmanager
def account_lock():
    lock_path = config_home() / 'omarchy/agents/add-account.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another account login is in progress. Finish it first.') from None
        yield


def register_codex_login(name):
    """Keep the CLI launcher usable after the dialog creates an explicit list."""
    if not re.fullmatch('[a-z0-9][a-z0-9_-]{0,47}', name):
        raise ValueError('Invalid Codex account label.')
    provider = PROVIDERS['openai']
    path = config_path(provider)
    directory = Path.home() / ('.codex-' + name)
    account_id = 'codex-' + name
    with account_lock():
        if not path.exists():
            return  # Directory discovery already includes this login.
        data = read_config(provider)
        for row in data['accounts']:
            raw = row.get('id') or Path(row.get('configDir', '')).name.lstrip('.')
            row_id = normalized_id(provider, raw)
            row_dir = Path(row.get('configDir') or Path.home() / ('.' + row_id)).expanduser()
            if row_dir.resolve() == directory.resolve():
                return  # Preserve configured names and disabled accounts.
            if row_id == account_id:
                raise ValueError('Login saved, but its account id is configured with another directory.')
        data['accounts'].append({'id': account_id, 'name': 'Codex · ' + name,
                                 'configDir': str(directory)})
        save_config(path, data)


def authenticate(provider_id, name):
    # Serialize registration and login so our terminals cannot overwrite an
    # account or lose one another's configuration updates.
    with account_lock():
        plan = prepare(provider_id, name)
        provider = plan['provider']
        path = config_path(provider)
        data = read_config(provider)
        original = path.read_bytes() if path.exists() else None
        # Preserve accounts that were automatically discovered before creating
        # an explicit list. Keep disabled entries and unrelated settings too.
        known = {normalized_id(provider, row.get('id') or Path(row.get('configDir', '')).name.lstrip('.'))
                 for row in data['accounts']}
        for row in plan['discovered']:
            if row['id'] not in known:
                data['accounts'].append(row)
                known.add(row['id'])
        # Keep partial credentials outside discovery until login succeeds.
        reserved = False
        try:
            with tempfile.TemporaryDirectory(prefix='.omarchy-account-', dir=Path.home()) as temporary:
                staging = Path(temporary)
                command, env = login_command(dict(plan, directory=staging))
                print(f"Sign in to {provider['label']} for {plan['name']}.\n", flush=True)
                result = subprocess.run(command, env=env, cwd=staging)
                if result.returncode != 0 or not (staging / provider['credentials']).is_file():
                    raise ValueError('Login did not complete. No account was added; use + to try again.')
                plan['directory'].mkdir(mode=0o700)
                reserved = True
                os.replace(staging, plan['directory'])
        finally:
            # Only remove our empty reservation after a canceled/failed login.
            # A completed login or files written by another process stay intact.
            if reserved:
                try:
                    plan['directory'].rmdir()
                except OSError:
                    pass
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError('Account settings changed during login. Your login is saved, but the account must be added to the settings manually.')
        data['accounts'].append({'id': plan['id'], 'name': plan['name'],
                                 'configDir': str(plan['directory'])})
        save_config(path, data)
        print('\nAccount added. Refreshing usage…', flush=True)
        refresh(plan)
        return plan


def prepare_reauthentication(provider_id, name, account_id, config_dir):
    provider = PROVIDERS.get(provider_id)
    if not provider or not account_id:
        raise ValueError('Choose a supported local account.')
    family = provider['family']
    if account_id != family and not account_id.startswith(family + '-'):
        raise ValueError('The account does not belong to this provider.')
    default = Path(os.environ.get(provider['env']) or Path.home() / ('.' + family)).expanduser().resolve()
    if account_id == family:
        directory = default
    elif config_dir:
        directory = Path(config_dir).expanduser().resolve()
        if directory == default:
            raise ValueError('This extra account points to the default login. Fix its account folder first.')
    else:
        raise ValueError('This account has no local login folder.')
    if not directory.is_dir():
        raise ValueError('The account login folder no longer exists.')
    if not shutil.which(provider['login'][0]):
        raise ValueError(f"Install {provider['login'][0]} before signing in.")
    return {'provider': provider, 'name': name, 'id': account_id, 'directory': directory}


def reauthenticate(provider_id, name, account_id, config_dir):
    with account_lock():
        plan = prepare_reauthentication(provider_id, name, account_id, config_dir)
        command, env = login_command(plan)
        print(f"Sign in to {plan['provider']['label']} for {plan['name']}.\n"
              f"Account folder: {plan['directory']}\n"
              'Choose the intended account in your browser.\n', flush=True)
        # Let the provider replace its own login in this exact directory.
        # Do not log out first or recreate the account and its settings.
        result = subprocess.run(command, env=env, cwd=plan['directory'])
        if result.returncode != 0 or not (plan['directory'] / plan['provider']['credentials']).is_file():
            raise ValueError('Sign-in did not complete. Use re-auth to try again.')
        print('\nSign-in complete. Refreshing usage…', flush=True)
        refresh(plan)
        return plan


def launch_terminal(action, *arguments):
    if not shutil.which('xdg-terminal-exec'):
        raise ValueError('No terminal launcher found (xdg-terminal-exec).')
    terminal = subprocess.Popen(['xdg-terminal-exec', '--dir=' + str(Path.home()),
                                 sys.executable, str(Path(__file__).resolve()), action, '--',
                                 *arguments], start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    # Some terminals stay alive for the whole session, others hand off to an
    # existing process. Detect immediate failures without timing out the login.
    try:
        if terminal.wait(timeout=0.5) != 0:
            raise ValueError('The terminal could not start. Check your default terminal.')
    except subprocess.TimeoutExpired:
        pass


def launch(provider_id, name):
    prepare(provider_id, name)
    launch_terminal('authenticate', provider_id, name)


def launch_reauthentication(provider_id, name, account_id, config_dir):
    plan = prepare_reauthentication(provider_id, name, account_id, config_dir)
    launch_terminal('reauthenticate', provider_id, name, account_id, str(plan['directory']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['providers', 'launch', 'authenticate', 'register',
                                         'launch-reauth', 'reauthenticate'])
    parser.add_argument('provider', nargs='?')
    parser.add_argument('name', nargs='?')
    parser.add_argument('account_id', nargs='?')
    parser.add_argument('config_dir', nargs='?', default='')
    args = parser.parse_args()
    status = 0
    try:
        if args.action == 'providers':
            print(json.dumps([{'value': key, 'label': value['label']} for key, value in PROVIDERS.items()]))
        elif args.provider is None or args.name is None:
            raise ValueError('Choose a provider and enter an account name.')
        elif args.action == 'launch':
            launch(args.provider, args.name)
        elif args.action == 'launch-reauth':
            launch_reauthentication(args.provider, args.name, args.account_id, args.config_dir)
        elif args.action == 'reauthenticate':
            reauthenticate(args.provider, args.name, args.account_id, args.config_dir)
        elif args.action == 'register':
            if args.provider != 'openai':
                raise ValueError('CLI registration is only supported for Codex.')
            register_codex_login(args.name)
        else:
            authenticate(args.provider, args.name)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        status = 1
    except KeyboardInterrupt:
        print('\nLogin canceled.', file=sys.stderr)
        status = 1
    if args.action in ('authenticate', 'reauthenticate') and sys.stdin.isatty():
        try:
            input('\nPress Enter to close this terminal.')
        except (EOFError, KeyboardInterrupt):
            pass
    return status


if __name__ == '__main__':
    sys.exit(main())
