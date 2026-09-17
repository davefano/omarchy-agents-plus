from datetime import datetime
import os
import time
import unittest
from unittest.mock import patch

from reset_times import reset_label


class ResetTimesTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, TZ='America/New_York')
        env.start()
        time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(env.stop)
        self.now = datetime.fromisoformat('2026-09-16T20:00:00+00:00')

    def test_tomorrow_in_eastern(self):
        self.assertEqual(reset_label('2026-09-17T13:00:00Z', self.now),
                         'Resets tomorrow at 9 a.m. EDT')

    def test_source_offsets_represent_same_instant(self):
        utc = reset_label('2026-09-17T13:15:00Z', self.now)
        self.assertEqual(utc, reset_label('2026-09-17T22:15:00+09:00', self.now))
        self.assertEqual(utc, 'Resets tomorrow at 9:15 a.m. EDT')

    def test_today_weekday_and_later_date(self):
        self.assertEqual(reset_label('2026-09-17T01:00:00Z', self.now), 'Resets today at 9 p.m. EDT')
        self.assertEqual(reset_label('2026-09-19T08:13:00Z', self.now), 'Resets on Saturday at 4:13 a.m. EDT')
        self.assertEqual(reset_label('2026-09-30T16:00:00Z', self.now), 'Resets on Wed, Sep 30 at 12 p.m. EDT')

    def test_local_midnight_and_noon(self):
        self.assertEqual(reset_label('2026-09-17T04:00:00Z', self.now), 'Resets tomorrow at 12 a.m. EDT')
        self.assertEqual(reset_label('2026-09-17T16:00:00Z', self.now), 'Resets tomorrow at 12 p.m. EDT')

    def test_spring_dst_uses_calendar_days(self):
        now = datetime.fromisoformat('2026-03-07T17:00:00+00:00')
        self.assertEqual(reset_label('2026-03-08T16:00:00Z', now), 'Resets tomorrow at 12 p.m. EDT')

    def test_autumn_dst_uses_reset_offset(self):
        now = datetime.fromisoformat('2026-11-01T04:00:00+00:00')
        self.assertEqual(reset_label('2026-11-01T05:30:00Z', now), 'Resets today at 1:30 a.m. EDT')
        self.assertEqual(reset_label('2026-11-01T06:30:00Z', now), 'Resets today at 1:30 a.m. EST')

    def test_switch_to_pacific(self):
        os.environ['TZ'] = 'America/Los_Angeles'
        time.tzset()
        self.assertEqual(reset_label('2026-09-17T13:00:00Z', self.now), 'Resets tomorrow at 6 a.m. PDT')

    def test_stale_and_unknown_timestamps(self):
        self.assertEqual(reset_label('2026-09-16T13:00:00Z', self.now),
                         'Reset was today at 9 a.m. EDT · refresh to update')
        for value in ('', 'invalid', '2026-09-17T09:00:00', None):
            self.assertEqual(reset_label(value, self.now), 'Reset time unavailable')


if __name__ == '__main__':
    unittest.main()
