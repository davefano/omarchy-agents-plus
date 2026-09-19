#!/usr/bin/env python3
"""Discover Grok logins and collect the CLI's account allowance."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request

from refresh_usage import wanted
from account_identity import read_object

MANAGED_BY = 'davidfano.grok-accounts'
BILLING_URL = 'https://cli-chat-proxy.grok.com/v1/billing?format=credits'


def billing_fields(payload):
    """Map the official CLI's credits response; absent proto scalars mean zero.

    Matches grok-build's extensions/billing.rs and
    pager/app/effects/helpers.rs::credit_balance_from_config.
    A missing config is unavailable, never a zero-percent allowance.
    """
    config = payload.get('config')
    if config is None:
        return {'limits': [], 'usageNote': 'Grok has no billing data for this login.'}
    if not isinstance(config, dict):
        raise ValueError('Invalid billing config')

    def number(value):
        if isinstance(value, bool):
            raise ValueError('Invalid billing number')
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Invalid billing number')
        return result

    def cents(key):
        value = config.get(key) or {}
        return number(value.get('val', 0))

    period = config.get('currentPeriod') or {}
    kind = period.get('type', '')
    label = 'Weekly' if kind == 'USAGE_PERIOD_TYPE_WEEKLY' else (
        'Monthly' if kind == 'USAGE_PERIOD_TYPE_MONTHLY' else 'Usage')
    percent = config.get('creditUsagePercent')
    if percent is None:
        limit = cents('monthlyLimit')
        percent = cents('used') / limit * 100 if limit > 0 else 0
        if limit > 0 and not kind:
            label = 'Monthly'
    percent = min(100, max(0, number(percent)))
    return {'limits': [{'label': label, 'percent': percent,
                        'resetsAt': str(period.get('end') or config.get('billingPeriodEnd') or '')}],
            'tierLabel': str(payload.get('subscription_tier') or 'Grok Build'),
            'usageNote': 'Account allowance from Grok. Daily token history is not connected yet.'}


def collect_billing(directory, previous, force=False):
    sessions = [row for row in read_object(directory / 'auth.json').values()
                if isinstance(row, dict) and row.get('key')]
    if len(sessions) != 1:
        return {'limits': [], 'usageNote': 'Re-authenticate to select a single Grok login.'}
    auth = sessions[0]
    token, user_id = auth.get('key'), auth.get('user_id')
    if not isinstance(token, str) or not isinstance(user_id, str) or not user_id:
        return {'limits': [], 'usageNote': 'Re-authenticate to connect Grok account usage.'}
    # Never reuse one identity's allowance after re-auth or a config-dir change.
    fingerprint = hashlib.sha256((str(directory.resolve()) + '\0' + token).encode()).hexdigest()
    same_login = previous.get('billingLoginHash') == fingerprint
    now = time.time()
    try:
        age = now - float(previous.get('billingAttemptAt', 0))
    except (TypeError, ValueError):
        age = float('inf')
    keys = ('limits', 'tierLabel', 'usageNote', 'billingFetchedAt', 'billingAttemptAt', 'billingLoginHash')
    cached = {key: previous[key] for key in keys if key in previous} if same_login else {}
    if same_login and not force and 0 <= age < 60:
        return cached
    request = urllib.request.Request(BILLING_URL, headers={
        'Authorization': 'Bearer ' + token, 'X-XAI-Token-Auth': 'xai-grok-cli',
        'x-userid': user_id, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            fields = billing_fields(json.load(response))
        fields['billingFetchedAt'] = now
    except urllib.error.HTTPError as error:
        fields = cached or {'limits': []}
        if error.code in (401, 403):
            fields = {'limits': [], 'usageNote': 'Grok login needs attention. Click re-auth to reconnect usage.'}
        else:
            fields['usageNote'] = 'Grok usage refresh failed (HTTP ' + str(error.code) + ').' + (
                ' Showing the last successful reading.' if fields.get('limits') else ' Try refreshing.')
    except (OSError, ValueError, TypeError, AttributeError):
        fields = cached or {'limits': []}
        fields['usageNote'] = 'Unable to refresh Grok usage.' + (
            ' Showing the last successful reading.' if fields.get('limits') else ' Try refreshing.')
    fields.update(billingAttemptAt=now, billingLoginHash=fingerprint)
    return fields


def default_directory():
    return Path(os.environ.get('GROK_HOME') or Path.home() / '.grok').expanduser().resolve()


def accounts():
    """Extra accounts only; the default login is discovered separately."""
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'omarchy/agents/grok-accounts.json'
    if config.exists():
        rows = json.loads(config.read_text())['accounts']
        if not isinstance(rows, list):
            raise ValueError('Grok accounts must be an array.')
    else:
        rows = [{'id': p.name.removeprefix('.grok-'), 'configDir': str(p)}
                for p in sorted(home.glob('.grok-*')) if (p / 'auth.json').is_file()]
    result, ids, directories = [], set(), {default_directory()}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid Grok account entry.')
        if row.get('enabled', True) is False:
            continue
        raw = str(row.get('id') or Path(row.get('configDir', '')).name.lstrip('.'))
        key = re.sub('[^a-z0-9._-]+', '-', raw.lower()).strip('._-')
        if not key or key == 'grok':
            raise ValueError('Extra Grok accounts need a non-default id.')
        key = key if key.startswith('grok-') else 'grok-' + key
        directory = Path(row.get('configDir') or home / ('.' + key)).expanduser().resolve()
        if directory == default_directory():
            continue
        if key in ids or directory in directories:
            raise ValueError('Duplicate Grok account id or directory.')
        ids.add(key)
        directories.add(directory)
        result.append({'id': key, 'name': row.get('name') or 'Grok · ' + key[5:],
                       'configDir': str(directory)})
    return result


def publish(account, usage, force=False):
    directory = Path(account['configDir'])
    record = dict(account, managedBy=MANAGED_BY, accountAvailable=True,
                  ready=(directory / 'auth.json').is_file(), tierLabel='CLI account', limits=[], recentDays=[],
                  hasLocalStats=False, hasPromptStats=False)
    previous = read_object(usage / (account['id'] + '.json'))
    record.update(collect_billing(directory, previous, force))
    usage.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + account['id'], dir=usage)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(record, handle)
        os.replace(temporary, usage / (account['id'] + '.json'))
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--limits-only', action='store_true')
    parser.add_argument('--except', dest='excluded', action='append', default=[])
    parser.add_argument('ids', nargs='*')
    args = parser.parse_args(argv)
    resolved = accounts()  # A broken config must not prune valid records.
    if args.ids == ['list']:
        print(json.dumps(resolved))
        return
    default = default_directory()
    if (default / 'auth.json').is_file():
        resolved.insert(0, {'id': 'grok', 'name': 'Grok', 'configDir': str(default)})
    usage = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'omarchy/agents/usage'
    active = {account['id'] for account in resolved}
    flags = [value for account_id in args.excluded for value in ('--except', account_id)] + args.ids
    for account in resolved:
        if wanted(account['id'], flags):
            publish(account, usage, args.force)
    for path in usage.glob('grok*.json'):
        if path.stem in active:
            continue
        try:
            if json.loads(path.read_text()).get('managedBy') == MANAGED_BY:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass


if __name__ == '__main__':
    main()
