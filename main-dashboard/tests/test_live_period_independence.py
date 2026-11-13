import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from get_dashboard_snapshot import timely_live_comparison


def metrics(attend=8, expected=10, **flags):
    return {"liveExpected": expected, "liveAttend": attend,
            "liveExpectedList": [{"id": str(i), "name": str(i)} for i in range(expected)],
            "liveAttendList": [{"id": str(i), "name": str(i)} for i in range(attend)], **flags}


class LivePeriodIndependenceTests(unittest.TestCase):
    def test_missing_previous_board_keeps_current_total_and_slots(self):
        result = timely_live_comparison([
            {"slot": "Friday", "current": metrics(8), "previous": metrics(7)},
            {"slot": "Saturday", "current": metrics(9), "previous": metrics(0, 0, missingLiveBoards=1)},
        ])
        self.assertEqual(result["currentRate"], .85)
        self.assertFalse(result["currentPending"])
        self.assertTrue(result["previousPending"])
        self.assertIsNone(result["previousRate"])
        self.assertIsNone(result["gap"])
        self.assertFalse(result["hasBaseline"])
        self.assertEqual(result["slotCount"], 2)
        self.assertEqual(result["slots"][1]["currentRate"], .9)
        self.assertEqual(result["attendanceChanges"]["lastWeekCameThisWeekMissed"], [])

    def test_missing_current_board_keeps_verified_previous_total(self):
        result = timely_live_comparison([
            {"slot": "Friday", "current": metrics(8), "previous": metrics(7)},
            {"slot": "Saturday", "current": metrics(0, 0, livePending=True), "previous": metrics(9)},
        ])
        self.assertTrue(result["currentPending"])
        self.assertFalse(result["previousPending"])
        self.assertIsNone(result["currentRate"])
        self.assertEqual(result["previousRate"], .8)
        self.assertIsNone(result["gap"])
        self.assertFalse(result["hasBaseline"])
        self.assertEqual(result["slots"][1]["previousRate"], .9)
        self.assertEqual(result["attendanceChanges"]["lastWeekMissedThisWeekCame"], [])

    def test_complete_zero_attendance_is_valid_and_comparable(self):
        result = timely_live_comparison([
            {"slot": "Friday", "current": metrics(0), "previous": metrics(7)},
        ])
        self.assertFalse(result["livePending"])
        self.assertEqual(result["currentRate"], 0)
        self.assertEqual(result["previousRate"], .7)
        self.assertEqual(result["gap"], -.7)
        self.assertTrue(result["hasBaseline"])
        self.assertEqual(len(result["attendanceChanges"]["lastWeekCameThisWeekMissed"]), 7)


if __name__ == "__main__":
    unittest.main()
