import sys
import unittest
import tempfile
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from weekly_attendance_table import SHEET_NAME, build_weekly_attendance_table, verify_weekly_attendance_sheet, write_weekly_attendance_sheet
from audit_weekly_rosters import latest_class_roster
FIXED_HEADER = ["老师", "课线", "课期", "在读人数", "上课时间"]


def metrics(expected, attend, replay):
    wrap = lambda values: [{"id": value} for value in values]
    return {"liveExpected": len(expected), "liveRate": len(attend) / len(expected),
            "liveExpectedList": wrap(expected), "liveAttendList": wrap(attend), "replayList": wrap(replay)}


class WeeklyAttendanceTests(unittest.TestCase):
    def test_configured_previous_and_current_weeks_are_kept(self):
        snapshot = self.snapshot()
        snapshot["updatedAt"] = "2026-10-25 20:00:00"
        snapshot["weeklyAttendanceClasses"] = snapshot["classes"]
        for item in snapshot["weeklyAttendanceClasses"]:
            item["attendanceWeeks"] = {"2026-10-19": item["current"], "2026-10-26": {}}
        table = build_weekly_attendance_table(snapshot)
        self.assertEqual(table["weeks"], ["2026-10-12", "2026-10-19"])
        self.assertEqual(table["data"][0][5], 1)
        self.assertEqual(table["data"][0][16], 1)
        snapshot["updatedAt"] = "2026-10-26 09:00:00"
        table = build_weekly_attendance_table(snapshot)
        self.assertEqual(table["weeks"], ["2026-10-19", "2026-10-26"])
        self.assertTrue(all(row[13] == row[3] and all(value is None for value in row[14:]) for row in table["data"] if row[1] != "汇总"))

    def snapshot(self):
        return {"rows": [{"teacher": "T", "cohort": "C", "currentWeek": "2026-10-19周", "previousWeek": "2026-10-05周"}],
                "classes": [{"teacher": "T", "cohort": "C", "classId": 1, "slot": "周五晚", "students": [{"id": "1"}],
                             "current": metrics(["1", "2"], ["1"], ["1", "2", "outside"]),
                             "previous": metrics(["1", "2"], ["1"], [])},
                            {"teacher": "T", "cohort": "C", "classId": 2, "slot": "周六午", "students": [{"id": "3"}],
                             "current": metrics(["3", "4", "5", "6"], ["3"], []), "previous": {}}]}

    def test_replay_union_and_weighted_average_skip_unopened_week(self):
        table = build_weekly_attendance_table(self.snapshot())
        self.assertEqual(table["weeks"], ["2026-10-05", "2026-10-19"])
        current = table["data"][0][13:]
        self.assertEqual(current[:4], [1, None, None, 1])
        self.assertEqual(current[5], 0)
        self.assertEqual(current[7], 1)
        self.assertEqual(table["data"][1][5:13], [1, None, None, None, None, None, None, None])

    def test_duplicate_classes_do_not_duplicate_students(self):
        snapshot = self.snapshot()
        snapshot["classes"].append(snapshot["classes"][0])
        table = build_weekly_attendance_table(snapshot)
        self.assertEqual(table["data"][0][13], 1)
        self.assertEqual(table["data"][0][3], 1)

    def test_previous_and_current_week_data_are_kept(self):
        snapshot = self.snapshot()
        snapshot["updatedAt"] = "2026-10-26 09:00:00"
        snapshot["weeklyAttendanceWeeks"] = ["2026-10-19", "2026-10-26"]
        snapshot["weeklyAttendanceClasses"] = snapshot["classes"]
        for item in snapshot["weeklyAttendanceClasses"]:
            item["attendanceWeeks"] = {"2026-10-19": item["current"], "2026-10-26": {}}
        table = build_weekly_attendance_table(snapshot)
        self.assertEqual(table["weeks"], ["2026-10-19", "2026-10-26"])
        self.assertEqual(table["data"][0][5], 1)
        self.assertEqual(table["data"][0][13], 1)
        self.assertEqual(table["data"][0][16], None)

    def test_stopped_or_empty_live_week_does_not_fail(self):
        snapshot = self.snapshot()
        snapshot["weeklyAttendanceClasses"] = [{
            "teacher": "T", "coursePackage": "C", "cohort": "C", "slot": "周五晚",
            "classId": 99, "students": [{"id": "1"}],
            "attendanceWeeks": {"2026-10-19": {}, "2026-10-26": {}}
        }]
        snapshot["updatedAt"] = "2026-10-20 09:00:00"
        table = build_weekly_attendance_table(snapshot)
        self.assertEqual(len(table["data"]), 2)
        self.assertEqual(table["data"][0][5], 1)
        self.assertEqual(table["data"][0][13], 1)
        self.assertIsNone(table["data"][0][8])

    def test_unverified_data_remains_blank(self):
        snapshot = self.snapshot()
        snapshot["classes"][0]["current"]["missingLiveBoards"] = 1
        table = build_weekly_attendance_table(snapshot)
        self.assertEqual(table["data"][0][13:], [1, None, None, *["待更新"] * 5])
        self.assertEqual(table["data"][0][13], table["data"][0][3])

    def test_workbook_verification_accepts_numeric_strings_but_rejects_bad_counts(self):
        table = build_weekly_attendance_table(self.snapshot())
        rows = [["" if value is None else str(value) for value in row[3:]] for row in table["data"]]
        core = SimpleNamespace(WORKBOOK="workbook", col_letter=lambda index: "W",
                               mcp_call=Mock(return_value=rows), find_rows=lambda value: value)
        verify_weekly_attendance_sheet(core, "sheet", table)
        rows[0][0] = "999"
        with self.assertRaisesRegex(RuntimeError, "VERIFY_FAILED"):
            verify_weekly_attendance_sheet(core, "sheet", table)

    def test_latest_roster_excludes_historical_students(self):
        block = {"lessons": [{"course_id": 1, "unlock_time": 100, "course_number": 1},
                             {"course_id": 2, "unlock_time": 200, "course_number": 2}],
                 "items": [{"course_id": 1, "user_id": "past"}, {"course_id": 1, "user_id": "active"},
                           {"course_id": 2, "user_id": "active"}],
                 "liveAttendance": {"1": {"names": {"room-only": "X"}}}}
        course, roster = latest_class_roster(block)
        self.assertEqual(course, 2)
        self.assertEqual(set(roster), {"active"})

    def test_verification_keeps_manual_invitation_values(self):
        table = build_weekly_attendance_table(self.snapshot())
        rows = [list(row[3:]) for row in table["data"]]
        for row in rows:
            row[3], row[4], row[11], row[12] = 17, .17, "周五发", ""
        core = SimpleNamespace(WORKBOOK="workbook", col_letter=lambda index: "U",
                               mcp_call=Mock(return_value=rows), find_rows=lambda value: value)
        verify_weekly_attendance_sheet(core, "sheet", table)

    def test_missing_target_never_creates_another_sheet(self):
        core = SimpleNamespace(load_sheet_ids=lambda: {}, mcp_call=Mock())
        with self.assertRaisesRegex(RuntimeError, "TARGET_MISSING"):
            write_weekly_attendance_sheet(core, build_weekly_attendance_table(self.snapshot()))
        core.mcp_call.assert_not_called()

    def fake_sheet(self, table, change_on_read=False, allow_rollover=False):
        rows = [list(FIXED_HEADER) + [v for week in table["weeks"] for v in [week + "周"] + [""] * 7],
                [""] * len(table["columns"]), *[list(row) for row in table["data"]]]
        # Simulate merged teacher/cohort cells as returned by DingTalk.
        rows[3][:3] = ["", "", ""]
        rows[2][6], rows[3][14] = 0, "周五发"
        def col(index):
            return chr(65 + index)
        reads = 0
        def call(method, args):
            nonlocal reads
            if method == "get_range":
                reads += 1
                if args["range"].startswith("D3"):
                    return [row[3:] for row in rows[2:]]
                result = [list(row) for row in rows]
                if change_on_read and reads == 1:
                    rows[2][6] = 23  # A teacher edits after the updater's read.
                return result
            if method == "update_range" and "values" in args:
                address = args["rangeAddress"]
                match = re.fullmatch(r"([A-Z])([0-9]+):([A-Z])([0-9]+)", address)
                self.assertIsNotNone(match)
                left, top, right, bottom = match.groups()
                if not allow_rollover:
                    self.assertFalse(ord(left) <= ord("G") <= ord(right))
                    self.assertFalse(ord(left) <= ord("O") <= ord(right))
                for offset, value_row in enumerate(args["values"]):
                    rows[int(top) - 1 + offset][ord(left) - 65:ord(right) - 64] = value_row
            elif method == "unmerge_range" and allow_rollover:
                self.assertIn(args["rangeAddress"], ["F1:M1", "N1:U1"])
            elif method in ("clear_range", "unmerge_range"):
                self.fail("A stable layout must never clear or unmerge")
        core = SimpleNamespace(WORKBOOK="workbook", load_sheet_ids=lambda: {SHEET_NAME: "sheet"},
                               col_letter=col, find_rows=lambda value: value, mcp_call=Mock(side_effect=call))
        return core, rows

    def test_stable_refresh_never_writes_manual_columns_even_during_teacher_edit(self):
        table = build_weekly_attendance_table(self.snapshot())
        core, rows = self.fake_sheet(table, change_on_read=True)
        with tempfile.TemporaryDirectory() as directory, patch("weekly_attendance_table.WEEKLY_HASH_FILE", Path(directory) / "hash.json"):
            self.assertEqual(write_weekly_attendance_sheet(core, table), len(table["data"]))
        self.assertEqual(rows[2][6], 23)
        self.assertEqual(rows[3][14], "周五发")
        self.assertEqual([c.args[1]["rangeAddress"] for c in core.mcp_call.call_args_list if c.args[0] == "update_range"],
                         ["D3:E5", "N3:N5", "P3:U5"])

    def test_layout_change_with_manual_values_stops_before_any_mutation(self):
        table = build_weekly_attendance_table(self.snapshot())
        core, rows = self.fake_sheet(table)
        rows[2][2] = "different cohort"
        with tempfile.TemporaryDirectory() as directory, patch("weekly_attendance_table.WEEKLY_HASH_FILE", Path(directory) / "hash.json"):
            with self.assertRaisesRegex(RuntimeError, "INVITES_LAYOUT_CHANGED"):
                write_weekly_attendance_sheet(core, table)
        self.assertEqual([c.args[0] for c in core.mcp_call.call_args_list], ["get_range"])
        self.assertEqual(rows[2][6], 0)

    def test_week_rollover_with_manual_values_stops_before_any_mutation(self):
        table = build_weekly_attendance_table(self.snapshot())
        core, rows = self.fake_sheet(table)
        rows[0][5] = "2026-09-28周"
        with tempfile.TemporaryDirectory() as directory, patch("weekly_attendance_table.WEEKLY_HASH_FILE", Path(directory) / "hash.json"):
            with self.assertRaisesRegex(RuntimeError, "INVITES_LAYOUT_CHANGED"):
                write_weekly_attendance_sheet(core, table)
        self.assertEqual([c.args[0] for c in core.mcp_call.call_args_list], ["get_range"])

    def rollover_tables(self):
        snapshot = self.snapshot()
        snapshot["weeklyAttendanceWeeks"] = ["2026-10-19", "2026-10-26"]
        old = build_weekly_attendance_table(snapshot)
        snapshot["weeklyAttendanceWeeks"] = ["2026-10-26", "2026-11-02"]
        new = build_weekly_attendance_table(snapshot)
        return old, new

    def test_rollover_moves_complete_previous_week_and_preserves_zero_and_text_invites(self):
        old, new = self.rollover_tables()
        core, rows = self.fake_sheet(old, allow_rollover=True)
        rows[2][13:21] = [10, 0, 0, 7, .7, 2, .2, .9]
        rows[3][13:21] = [20, "周五发", "", 10, .5, 3, .15, .65]
        historical = [list(row[13:21]) for row in rows[2:]]
        with tempfile.TemporaryDirectory() as directory, patch("weekly_attendance_table.WEEKLY_HASH_FILE", Path(directory) / "hash.json"):
            write_weekly_attendance_sheet(core, new)
        self.assertEqual(rows[0][5], "2026-10-26周")
        self.assertEqual(rows[0][13], "2026-11-02周")
        for index, values in enumerate(historical):
            self.assertEqual(rows[index + 2][5:7], values[:2])
            self.assertEqual(rows[index + 2][8:13], values[3:])
            self.assertIn("G", rows[index + 2][7])
            self.assertIsNone(rows[index + 2][14])
        addresses = [c.args[1]["rangeAddress"] for c in core.mcp_call.call_args_list if c.args[0] == "update_range"]
        self.assertEqual(addresses, ["F1:U5", "D3:E5"])

    def test_rollover_cancels_if_teacher_changes_invite_after_read(self):
        old, new = self.rollover_tables()
        core, rows = self.fake_sheet(old, change_on_read=True, allow_rollover=True)
        with tempfile.TemporaryDirectory() as directory, patch("weekly_attendance_table.WEEKLY_HASH_FILE", Path(directory) / "hash.json"):
            with self.assertRaisesRegex(RuntimeError, "INVITES_CHANGED"):
                write_weekly_attendance_sheet(core, new)
        self.assertFalse(any(c.args[0] == "update_range" for c in core.mcp_call.call_args_list))
        self.assertEqual(rows[2][6], 23)

    def test_stable_refresh_does_not_recalculate_last_weeks_historical_counts(self):
        old, _ = self.rollover_tables()
        core, rows = self.fake_sheet(old)
        rows[2][5:13] = [99, 7, .07, 80, .8, 10, .1, .9]
        historical = list(rows[2][5:13])
        with tempfile.TemporaryDirectory() as directory, patch("weekly_attendance_table.WEEKLY_HASH_FILE", Path(directory) / "hash.json"):
            write_weekly_attendance_sheet(core, old)
        self.assertEqual(rows[2][5:13], historical)

    def test_rollover_unmerges_only_headers_and_restores_them_when_write_fails(self):
        old, new = self.rollover_tables()
        core, rows = self.fake_sheet(old, allow_rollover=True)
        delegate = core.mcp_call.side_effect
        headers = {"F1:M1", "N1:U1"}
        def call(method, args):
            if method == "unmerge_range":
                headers.remove(args["rangeAddress"])
                return {"success": True}
            if method == "merge_cells":
                headers.add(args["rangeAddress"])
                return {"success": True}
            if method == "update_range" and args.get("rangeAddress", "").startswith("F1:"):
                self.assertEqual(headers, set())
                return {"success": False, "errorCode": "NETWORK_FAILURE"}
            return delegate(method, args)
        core.mcp_call.side_effect = call
        before = [list(row) for row in rows]
        with tempfile.TemporaryDirectory() as directory, patch("weekly_attendance_table.WEEKLY_HASH_FILE", Path(directory) / "hash.json"):
            with self.assertRaisesRegex(RuntimeError, "NETWORK_FAILURE"):
                write_weekly_attendance_sheet(core, new)
        self.assertEqual(headers, {"F1:M1", "N1:U1"})
        self.assertEqual(rows, before)
        self.assertFalse(any(c.args[0] == "update_range" and c.args[1].get("rangeAddress", "").startswith("D3") for c in core.mcp_call.call_args_list))

    def test_failed_invitation_read_never_clears_sheet(self):
        core = SimpleNamespace(WORKBOOK="workbook", load_sheet_ids=lambda: {SHEET_NAME: "sheet"},
                               col_letter=lambda index: "U", find_rows=lambda value: value,
                               mcp_call=Mock(side_effect=RuntimeError("network")))
        with patch("weekly_attendance_table.WEEKLY_HASH_FILE") as hashed:
            hashed.exists.return_value = False
            with self.assertRaisesRegex(RuntimeError, "INVITES_READ_FAILED"):
                write_weekly_attendance_sheet(core, build_weekly_attendance_table(self.snapshot()))
        self.assertEqual([call.args[0] for call in core.mcp_call.call_args_list], ["get_range"])


if __name__ == "__main__":
    unittest.main()




