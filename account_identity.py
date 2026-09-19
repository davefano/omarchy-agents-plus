#!/usr/bin/env python3
"""Read display-only identity for one saved login; never return credentials."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.request


def read_object(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def email_value(value):
    if not isinstance(value, str) or '@' not in value or len(value) > 320:
        return ''
    return value if not any(ord(c) < 32 for c in value) else ''


def claude_email(directory):
    login = read_object(directory / '.credentials.json').get('claudeAiOauth')
    token = login.get('accessToken') if isinstance(login, dict) else None
    if not isinstance(token, str) or not token:
        return {'email': '', 'status': 'No saved Claude login'}
    # Local .claude.json identity can outlive a login or differ between the
    # default and explicit CLAUDE_CONFIG_DIR layouts. Verify the token itself.
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    directory_hash = hashlib.sha256(str(directory).encode()).hexdigest()
    cache_home = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    cache_path = cache_home / 'omarchy/agents/identities' / (directory_hash + '.json')
    cached = read_object(cache_path)
    try:
        age = time.time() - float(cached.get('checkedAt', 0))
    except (TypeError, ValueError):
        age = float('inf')
    if cached.get('tokenHash') == token_hash and 0 <= age < 900 and email_value(cached.get('email')):
        return {'email': cached['email'], 'status': ''}
    request = urllib.request.Request('https://api.anthropic.com/api/oauth/profile',
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            profile = json.load(response)
        account = profile.get('account') if isinstance(profile, dict) else None
        email = email_value(account.get('email')) if isinstance(account, dict) else ''
    except (OSError, ValueError):
        return {'email': '', 'status': 'Unable to verify email. Try refreshing.'}
    if not email:
        return {'email': '', 'status': 'Email unavailable for this login'}
    # Cache only the email and a one-way login fingerprint, privately. A cache
    # failure must not hide an identity that was just verified successfully.
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.identity-', dir=cache_path.parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump({'email': email, 'tokenHash': token_hash, 'checkedAt': time.time()}, handle)
            os.replace(temporary, cache_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    except OSError:
        pass
    return {'email': email, 'status': ''}


def codex_email(directory):
    auth = read_object(directory / 'auth.json')
    tokens = auth.get('tokens')
    token = tokens.get('id_token') if isinstance(tokens, dict) else None
    if not isinstance(token, str):
        status = 'API key login · no account email' if auth.get('OPENAI_API_KEY') else 'No saved ChatGPT login'
        return {'email': '', 'status': status}
    try:
        payload = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        email = email_value(claims.get('email')) if isinstance(claims, dict) else ''
    except (ValueError, IndexError):
        email = ''
    # This is display metadata from the CLI's ID token, not authentication or
    # an authorization decision; no token ever leaves this process.
    return {'email': email, 'status': '' if email else 'Email unavailable for this login'}


def grok_email(directory):
    # Grok stores credentials by auth issuer/client. Do not guess which login
    # is active when this directory contains different saved identities.
    auth = read_object(directory / 'auth.json')
    sessions = [row for row in auth.values() if isinstance(row, dict) and row.get('key')]
    emails = {email_value(row.get('email')) for row in sessions}
    if len(emails) == 1 and '' not in emails:
        return {'email': emails.pop(), 'status': ''}
    if len(emails) > 1:
        return {'email': '', 'status': 'Multiple Grok identities in this folder'}
    return {'email': '', 'status': 'Email unavailable for this login' if sessions else 'No saved Grok login'}


def resolve(account_id, config_dir=''):
    family = account_id.split('-', 1)[0]
    if family not in ('claude', 'codex', 'grok'):
        return {'email': '', 'status': 'Email unavailable for this provider'}
    if account_id == family:
        variable = {'claude': 'CLAUDE_CONFIG_DIR', 'codex': 'CODEX_HOME', 'grok': 'GROK_HOME'}[family]
        directory = Path(os.environ.get(variable) or Path.home() / ('.' + family))
    elif config_dir:
        directory = Path(config_dir).expanduser()
    else:
        return {'email': '', 'status': 'No local login for this account'}
    directory = directory.resolve()
    return {'claude': claude_email, 'codex': codex_email, 'grok': grok_email}[family](directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('account_id')
    parser.add_argument('config_dir', nargs='?', default='')
    args = parser.parse_args()
    try:
        result = resolve(args.account_id, args.config_dir)
    except (OSError, ValueError, TypeError):
        result = {'email': '', 'status': 'Email unavailable for this login'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
