#!/usr/bin/env python3
"""Renew saved Claude logins through the CLI before collecting panel usage."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def login(config):
    try:
        data = json.loads((config / '.credentials.json').read_text()).get('claudeAiOauth', {})
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def fresh(data):
    try:
        return bool(data.get('accessToken')) and float(data.get('expiresAt', 0)) > (time.time() + 120) * 1000
    except (TypeError, ValueError):
        return False


def renew(config, cache):
    data = login(config)
    if fresh(data):
        return True
    if not data.get('refreshToken'):
        return False

    cache.mkdir(parents=True, exist_ok=True)
    lock_path = cache / (hashlib.sha256(str(config.resolve()).encode()).hexdigest() + '.lock')
    # Serialize our own refresh attempts; Claude Code handles credential locking,
    # refresh-token rotation, and coordination with other Claude Code processes.
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return fresh(login(config))
        if fresh(login(config)):
            return True
        try:
            last_attempt = float(lock.read() or 0)
        except ValueError:
            last_attempt = 0
        if time.time() - last_attempt < 300:
            return False
        lock.seek(0)
        lock.truncate()
        lock.write(str(time.time()))
        lock.flush()

        env = os.environ.copy()
        env['CLAUDE_CONFIG_DIR'] = str(config)
        # The selected directory must supply auth, not an inherited API key or
        # OAuth environment override intended for a different account.
        for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN',
                    'CLAUDE_CODE_OAUTH_REFRESH_TOKEN', 'CLAUDE_CODE_OAUTH_SCOPES'):
            env.pop(key, None)
        try:
            subprocess.run([
                'claude', '--safe-mode', '--setting-sources', '',
                '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                '--tools', '', '--no-session-persistence', '-p', '/usage',
            ], env=env, cwd=cache, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return fresh(login(config))


def wanted(account_id, args):
    excluded, selected = set(), set()
    args = iter(args)
    for arg in args:
        if arg == '--except':
            excluded.add(next(args, ''))
        elif not arg.startswith('-'):
            selected.add(arg)
    return account_id not in excluded and (not selected or account_id in selected)


def main():
    args = sys.argv[1:]
    home = Path.home()
    config_home = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    cache = Path(os.environ.get('XDG_CACHE_HOME') or home / '.cache') / 'omarchy/claude-renewal'
    helper = config_home / 'omarchy/plugins/linting.claude-accounts/bin/claude-accounts'
    accounts = [{'id': 'claude', 'configDir': str(home / '.claude')}]
    if helper.is_file():
        try:
            result = subprocess.run([str(helper), 'list'], capture_output=True, text=True, check=True, timeout=10)
            accounts.extend(json.loads(result.stdout))
        except (OSError, ValueError, subprocess.SubprocessError):
            print('agents: unable to discover extra Claude logins for renewal', file=sys.stderr)
    for account in accounts:
        if wanted(account['id'], args):
            try:
                renewed = renew(Path(account['configDir']), cache)
            except OSError:
                renewed = False
            if not renewed and login(Path(account['configDir'])).get('refreshToken'):
                print(f"agents: {account['id']}: renewal pending or failed; retaining saved login and cached usage", file=sys.stderr)
    status = subprocess.run(['omarchy-agent-usage-update', *args]).returncode
    if helper.is_file():
        extra_status = subprocess.run([str(helper), *args]).returncode
        status = status or extra_status
    codex_helper = Path(__file__).with_name('codex_accounts.py')
    if codex_helper.is_file():
        extra_status = subprocess.run([sys.executable, str(codex_helper), *args]).returncode
        status = status or extra_status
    grok_helper = Path(__file__).with_name('grok_accounts.py')
    if grok_helper.is_file():
        extra_status = subprocess.run([sys.executable, str(grok_helper), *args]).returncode
        status = status or extra_status
    return status


if __name__ == '__main__':
    sys.exit(main())
