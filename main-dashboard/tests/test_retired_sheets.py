import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_dashboard_update as dashboard
import console_data_api as console


class RetiredSheetTests(unittest.TestCase):
    def test_retired_dingtalk_sheets_are_never_written(self):
        self.assertTrue({"教学服务数据", "组内概览", "班级直播上座", "组内教学总看板"}.issubset(dashboard.DISABLED_SHEETS))
        for name in ("教学服务数据", "组内概览", "班级直播上座", "组内教学总看板"):
            with self.subTest(name=name), patch.object(dashboard, "mcp_call") as remote, \
                 patch.object(dashboard, "load_sheet_ids") as directory:
                self.assertEqual(dashboard.write_sheet(name, {"columns": ["老师"], "data": [["甲"]]}), 0)
                remote.assert_not_called()
                directory.assert_not_called()

    def test_local_console_still_exposes_retired_remote_views(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group, extra = root / "group.json", root / "extra.json"
            overview = {"columns": ["老师"], "data": [["甲"]]}
            live = {"columns": ["老师姓名"], "data": [["乙"]]}
            group.write_text(json.dumps({"sheets": {"组内概览": overview}}), encoding="utf-8")
            extra.write_text(json.dumps({"tables": {"班级直播上座": live}}), encoding="utf-8")
            with patch.object(console, "GROUP", group), patch.object(console, "EXCEPTION", extra):
                tables, _ = console.load_tables()
            self.assertEqual(tables["组内概览"], overview)
            self.assertEqual(tables["班级直播上座"], live)

    def test_local_teacher_validation_ignores_retired_live_sheet(self):
        tables = {
            "异常学员": {"columns": ["老师"], "data": [["甲"]]},
            "班级直播上座": {"columns": ["老师姓名"], "data": [["乙"]]},
            "课期异常": {"columns": ["老师"], "data": [["甲"]]},
        }
        self.assertEqual(dashboard.detail_teacher_sets(tables), {"异常学员": {"甲"}, "课期异常": {"甲"}})


if __name__ == "__main__":
    unittest.main()
