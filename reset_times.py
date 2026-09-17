#!/usr/bin/env python3
"""Format provider reset instants in the operating system's local time zone."""
from datetime import datetime, timezone
import json
import sys


def reset_label(timestamp, now=None):
    try:
        reset = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        # A timestamp without an offset is ambiguous; do not invent its zone.
        if reset.tzinfo is None:
            return 'Reset time unavailable'
        now = now or datetime.now(timezone.utc)
        local_reset = reset.astimezone()
        local_now = now.astimezone()
    except (TypeError, ValueError, AttributeError, OverflowError, OSError):
        return 'Reset time unavailable'

    days = (local_reset.date() - local_now.date()).days
    if days == 0:
        day = 'today'
    elif days == 1:
        day = 'tomorrow'
    elif 1 < days < 7:
        day = 'on ' + local_reset.strftime('%A')
    else:
        day = f"on {local_reset:%a, %b} {local_reset.day}"
        if local_reset.year != local_now.year:
            day += f', {local_reset.year}'

    hour = local_reset.hour % 12 or 12
    minutes = f':{local_reset.minute:02d}' if local_reset.minute else ''
    period = 'a.m.' if local_reset.hour < 12 else 'p.m.'
    zone = local_reset.tzname() or local_reset.strftime('UTC%z')
    at = f'{day} at {hour}{minutes} {period} {zone}'
    if reset <= now:
        return f'Reset was {at} · refresh to update'
    return f'Resets {at}'


def main():
    timestamps = json.loads(sys.argv[1])
    now = datetime.now(timezone.utc)
    # A fresh process uses current OS zone rules, including after travel or a
    # settings change. astimezone() applies the offset at the reset instant,
    # rather than assuming today's UTC offset will still apply then.
    print(json.dumps({timestamp: reset_label(timestamp, now) for timestamp in timestamps}))


if __name__ == '__main__':
    main()
