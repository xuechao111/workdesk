import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from get_dashboard_snapshot import CN, weekly_attendance_window
from weekly_attendance_table import build_weekly_attendance_table


class WeeklyCalendarWindowTests(unittest.TestCase):
    def weeks(self, timestamp):
        return [datetime.fromtimestamp(value, CN).strftime('%Y-%m-%d')
                for value in weekly_attendance_window(datetime.fromisoformat(timestamp).replace(tzinfo=CN).timestamp())]

    def test_friday_before_class_prepares_this_week(self):
        self.assertEqual(self.weeks('2026-11-06 09:00:00'), ['2026-10-26', '2026-11-02'])

    def test_rolls_on_monday_and_keeps_calendar_week_during_holiday(self):
        self.assertEqual(self.weeks('2026-11-08 23:59:59'), ['2026-10-26', '2026-11-02'])
        self.assertEqual(self.weeks('2026-11-09 00:00:00'), ['2026-11-02', '2026-11-09'])
        self.assertEqual(self.weeks('2026-10-09 09:00:00'), ['2026-09-28', '2026-10-05'])

    def test_unopened_current_week_has_expected_counts_and_blank_results(self):
        snapshot = {'updatedAt': '2026-11-06 09:00:00', 'weeklyAttendanceWeeks': self.weeks('2026-11-06 09:00:00'),
                    'weeklyAttendanceClasses': [{'teacher': 'T', 'coursePackage': 'P', 'cohort': 'C',
                        'classId': 1, 'slot': '周五晚', 'students': [{'id': '1'}, {'id': '2'}],
                        'attendanceWeeks': {'2026-10-26': {'liveExpected': 2, 'liveRate': .5,
                            'liveExpectedList': [{'id': '1'}, {'id': '2'}], 'liveAttendList': [{'id': '1'}]}, '2026-11-02': {}}}]}
        table = build_weekly_attendance_table(snapshot)
        self.assertEqual(table['weeks'], ['2026-10-26', '2026-11-02'])
        self.assertEqual(table['data'][0][8], 1)
        self.assertEqual(table['data'][0][13:], [2, None, None, None, None, None, None, None])


if __name__ == '__main__':
    unittest.main()
