"""Apply the authorized weekly rollover and audit the retained historical week."""
import json
from datetime import datetime
from pathlib import Path

import run_dashboard_update as core
import weekly_attendance_table as weekly


def main():
    lock = core.acquire_update_lock()
    if lock is None:
        raise RuntimeError("已有教学更新运行，未执行换周")
    try:
        # Use the independently verified sheet identity, never create a sheet.
        verified = json.loads((core.DATA / "weekly-rollover-before-20261106.json").read_text(encoding="utf-8"))
        if verified["nodeId"] != core.WORKBOOK:
            raise RuntimeError("已验证工作簿与当前配置不符")
        sheet_id = verified["sheetId"]
        original_loader = core.load_sheet_ids
        core.load_sheet_ids = lambda: {weekly.SHEET_NAME: sheet_id}
        base = {"nodeId": core.WORKBOOK, "sheetId": sheet_id}
        snapshot = json.loads((core.ROOT / "dashboard-snapshot.json").read_text(encoding="utf-8"))
        table = weekly.build_weekly_attendance_table(snapshot, core.dingtalk_excluded_teachers())
        before = core.find_rows(core.mcp_call("get_range", {**base, "range": "A1:U120"}))
        old_weeks, _, _ = weekly._weekly_layout(before)
        if old_weeks[1] != table["weeks"][0]:
            raise RuntimeError("不是连续换周，未执行迁移")
        audit = {"before": before, "weeks": table["weeks"], "sourceUpdatedAt": snapshot["updatedAt"]}
        audit_path = core.DATA / ("weekly-rollover-audit-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
        audit_path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
        count = weekly.write_weekly_attendance_sheet(core, table, snapshot["updatedAt"])
        after = core.find_rows(core.mcp_call("get_range", {**base, "range": "A1:U120"}))
        audit["after"] = after
        audit_path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
        if weekly._weekly_layout(after)[0] != table["weeks"]:
            raise RuntimeError("周次表头校验失败")
        normalize = lambda value: None if value == "" else value
        for old, new in zip(before[2:2 + count], after[2:2 + count]):
            for offset in (0, 1, 3, 4, 5, 6, 7):
                if normalize(old[13 + offset] if len(old) > 13 + offset else None) != normalize(new[5 + offset]):
                    raise RuntimeError("上周数据迁移校验失败")
            if len(new) > 14 and new[14] not in (None, ""):
                raise RuntimeError("新一周邀约填写栏应为空")
        print(json.dumps({"verified": True, "rows": count, "weeks": table["weeks"],
                          "preservedManualEntries": sum(len(row) > 14 and row[14] not in (None, "") for row in before[2:2 + count]),
                          "audit": audit_path.name}, ensure_ascii=False), flush=True)
        core.load_sheet_ids = original_loader
    finally:
        lock.close()


if __name__ == "__main__":
    main()
