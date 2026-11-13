"""Repair only the explicitly selected weekly attendance sheet."""
import json
import time
import subprocess
import sys
from datetime import datetime
import run_dashboard_update as core
from weekly_attendance_table import SHEET_NAME, build_weekly_attendance_table, write_weekly_attendance_sheet

if __name__ == "__main__":
    lock = core.acquire_update_lock()
    deadline = time.monotonic() + 300
    while lock is None and time.monotonic() < deadline:
        print("正在等待现有更新完成，避免并发写入…", flush=True)
        time.sleep(10)
        lock = core.acquire_update_lock()
    if lock is None:
        raise RuntimeError("现有更新仍在运行，未写入任何子表")
    try:
        subprocess.run([sys.executable, str(core.ROOT / "get_dashboard_snapshot.py")], check=True)
        snapshot = json.loads((core.ROOT / "dashboard-snapshot.json").read_text(encoding="utf-8"))
        table = build_weekly_attendance_table(snapshot, core.dingtalk_excluded_teachers())
        print(json.dumps({"target": SHEET_NAME, "weeks": table["weeks"], "rows": len(table["data"]),
                          "sourceTime": snapshot.get("updatedAt")}, ensure_ascii=False), flush=True)
        count = write_weekly_attendance_sheet(core, table, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print(f"周参播指定子表已写入并验证：{SHEET_NAME}，{count} 行；其他子表未写入", flush=True)
    finally:
        lock.close()
