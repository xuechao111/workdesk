"""Only skill-facing entrypoint for teaching audits, local builds and syncing."""
from __future__ import annotations
import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from runtime_paths import runtime_root
from teaching_metrics import lesson_pairs, period_metrics

ROOT = runtime_root()
CN = timezone(timedelta(hours=8))


def audit(output=None):
    raw_path = ROOT / "run-data/group-lessons-raw.json"
    snapshot_path = ROOT / "dashboard-snapshot.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    by_class = {int(b["classId"]): b for b in raw}
    now = int(datetime.now(CN).timestamp())
    records = []
    mismatches = []
    from get_dashboard_snapshot import eligible_block, teacher_name, course_package, week_start
    published = {int(c["classId"]): c for c in snapshot["classes"]}
    for cid, block in by_class.items():
        if not eligible_block(block, now):
            continue
        name = teacher_name(block.get("info", {}).get("teacherName"))
        cohort_start = week_start(min(int(l["unlock_time"]) for l in block["lessons"] if int(l.get("unlock_time") or 0) > 0))
        cohort = course_package(block) + " · " + datetime.fromtimestamp(cohort_start, CN).strftime("%Y-%m-%d周")
        teacher = next((r for r in snapshot["rows"] if r["teacher"] == name and r["cohort"] == cohort), {})
        c = published.get(cid, {"classId": cid, "teacher": name, "cohort": cohort})
        current_week = str(teacher.get("currentWeek") or c.get("currentWeek") or "").removesuffix("周")
        if not current_week:
            continue
        current_start = int(datetime.strptime(current_week, "%Y-%m-%d").replace(tzinfo=CN).timestamp())
        periods = [("current", current_start)]
        previous_week = str(teacher.get("previousWeek") or "").removesuffix("周")
        if previous_week:
            periods.append(("previous", int(datetime.strptime(previous_week, "%Y-%m-%d").replace(tzinfo=CN).timestamp())))
        for period, start in periods:
            m = period_metrics(block, start, start + 7 * 86400, now, allow_detail_live=bool(c.get(period, {}).get("detailLiveFallbacks")))
            outside_done, board_only, detail_only = 0, 0, 0
            for first, second in lesson_pairs(block):
                if not start <= int(second["unlock_time"]) < start + 7 * 86400 or int(second["unlock_time"]) > now:
                    continue
                detail = [i for i in block.get("items", []) if int(i.get("course_id") or 0) == int(second["course_id"])]
                ids = {str(i["user_id"]) for i in detail if i.get("user_id")}
                done = {str(i["user_id"]) for i in detail if i.get("user_id") and i.get("is_finish")}
                board = block.get("liveAttendance", {}).get(str(first["course_number"])) or block.get("liveAttendance", {}).get(first["course_number"])
                if board:
                    live = set(map(str, board.get("expectedIds", [])))
                    outside_done += len(done - live)
                    board_only += len(live - ids)
                    detail_only += len(ids - live)
            old = c.get(period)
            keys = ["arrivalExpected", "arrivalAttend", "liveExpected", "liveAttend", "evenExpected", "evenDone", "arrivedIncomplete"]
            diffs = {k: {"snapshot": old.get(k), "raw": m[k]} for k in keys if old.get(k) != m[k]} if old else {}
            if diffs:
                mismatches.append({"teacher": c["teacher"], "classId": c["classId"], "period": period, "fields": diffs})
            records.append({"老师": c["teacher"], "课期": c["cohort"], "班级ID": c["classId"], "周期": period,
                "统计周": datetime.fromtimestamp(start, CN).strftime("%Y-%m-%d"),
                "到课名单人数": m["arrivalExpected"], "到课人数": m["arrivalAttend"],
                "直播应到人数": m["liveExpected"], "直播人数": m["liveAttend"],
                "完课名单人数": m["evenExpected"], "完课人数": m["evenDone"],
                "直播名单外真实完课人数": outside_done, "直播独有名单人数": board_only, "课次独有名单人数": detail_only,
                "快照完课人数": old["evenDone"] if old else None, "快照需修正": bool(diffs), "本期已开课": bool(m["latestOpenedTime"]), "直播待核实": bool(m.get("missingLiveBoards") or m.get("detailLiveFallbacks"))})
    output = output or ROOT / "outputs" / ("统一教学核查-" + datetime.now(CN).strftime("%Y%m%d"))
    output.mkdir(parents=True, exist_ok=True)
    with (output / "全员班级核查.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    current = [r for r in records if r["周期"] == "current"]
    from collections import defaultdict
    teacher_totals = defaultdict(lambda: {"到课名单人数": 0, "到课人数": 0, "直播应到人数": 0, "直播人数": 0, "完课名单人数": 0, "完课人数": 0, "直播名单外真实完课人数": 0})
    for record in records:
        target = teacher_totals[(record["老师"], record["课期"], record["周期"], record["统计周"])]
        for key in target:
            target[key] += record[key]
    audit_fields = {"到课名单人数": "arrivalExpected", "到课人数": "arrivalAttend", "直播应到人数": "liveExpected", "直播人数": "liveAttend", "完课名单人数": "evenExpected", "完课人数": "evenDone"}
    for row in snapshot["rows"]:
        for period, week_key in (("current", "currentWeek"), ("previous", "previousWeek")):
            week = str(row.get(week_key) or "").removesuffix("周")
            totals = teacher_totals.get((row["teacher"], row["cohort"], period, week))
            if totals is None:
                continue
            diffs = {field: {"snapshot": row[period].get(field), "raw": totals[label]} for label, field in audit_fields.items() if row[period].get(field) != totals[label]}
            if diffs:
                mismatches.append({"teacher": row["teacher"], "cohort": row["cohort"], "period": period, "scope": "teacher-total", "fields": diffs})
    with (output / "全员老师汇总.csv").open("w", encoding="utf-8-sig", newline="") as f:
        headers = ["老师", "课期", "周期", "统计周", *next(iter(teacher_totals.values()))]
        writer = csv.writer(f)
        writer.writerow(headers)
        for key, values in sorted(teacher_totals.items()):
            writer.writerow([*key, *values.values()])
    summary = {"snapshotUpdatedAt": snapshot["updatedAt"], "rawModifiedAt": datetime.fromtimestamp(raw_path.stat().st_mtime, CN).isoformat(),
        "sourceClasses": len(raw), "sourceTeachers": len({teacher_name(b.get("info", {}).get("teacherName")) for b in raw}),
        "notYetOpenedOrExcludedClasses": sum(not eligible_block(b, now) for b in raw),
        "notYetOpenedOrExcludedTeachers": sorted({teacher_name(b.get("info", {}).get("teacherName")) for b in raw} - {r["老师"] for r in current}),
        "teachers": len({r["老师"] for r in current}), "classes": len(current),
        "arrivalExpected": sum(r["到课名单人数"] for r in current), "arrivalAttend": sum(r["到课人数"] for r in current),
        "liveExpected": sum(r["直播应到人数"] for r in current), "liveAttend": sum(r["直播人数"] for r in current),
        "evenExpected": sum(r["完课名单人数"] for r in current), "evenDone": sum(r["完课人数"] for r in current),
        "completedOutsideLiveRoster": sum(r["直播名单外真实完课人数"] for r in current),
        "previousCompletedOutsideLiveRoster": sum(r["直播名单外真实完课人数"] for r in records if r["周期"] == "previous"),
        "snapshotMismatchCount": len(mismatches), "mismatches": mismatches, "report": str(output / "全员班级核查.csv")}
    (output / "核查汇总.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["audit", "rebuild", "sync"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "audit":
        audit(args.output)
    elif args.mode == "rebuild":
        from run_dashboard_update import build_and_validate_local, acquire_update_lock
        lease = acquire_update_lock()
        if lease is None:
            raise RuntimeError("已有教学更新正在运行，请等待本轮完成后再重建。")
        try:
            build_and_validate_local()
        finally:
            lease.close()
        audit(args.output)
    else:
        # The normal runner owns its existing exclusive writer lease and keeps
        # every configured sheet's formats, follow-up columns and tail cleanup.
        import run_dashboard_update as core
        lease = core.acquire_update_lock()
        if lease is None:
            raise RuntimeError("已有教学更新正在运行，本次未重复写入，请等待该轮完成并核验状态。")
        try:
            core.run(from_raw=True)
        except Exception as error:
            core.set_status("error", "更新失败。", str(error))
            raise
        finally:
            lease.close()
        audit(args.output)


if __name__ == "__main__":
    main()
