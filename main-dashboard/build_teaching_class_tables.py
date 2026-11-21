"""Class tables built exclusively from the shared teaching metrics."""
from __future__ import annotations
import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from teaching_metrics import METRICS_CONTRACT_VERSION, lesson_pairs, period_metrics

CN = timezone(timedelta(hours=8))
CLASS_COLUMNS = ["主课期ID", "课期", "老师", "班级ID", "班级", "偶数课节", "偶数课课程名称", "配对第一节课", "第一节课应到人数", "第一节课到课人数", "到课率", "直播应到人数", "直播上座人数", "直播上座率", "应完课次数", "已完课次数", "到课未完课次数", "未到课次数", "未完课次数", "完课率"]
OVERVIEW_COLUMNS = ["主课期ID", "老师", "已开课班级数", "第一节课应到次数", "第一节课到课次数", "到课率", "直播应到次数", "直播上座次数", "直播上座率", "偶数课应完课次数", "偶数课已完课次数", "到课未完课次数", "偶数课未完课次数", "偶数课完课率"]

def week_start(value):
    dt = datetime.fromtimestamp(value, CN)
    return int((dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

def rate(done, expected):
    return done / expected if expected else 0

def make_table(columns, rows, texts, rates):
    return {"columns": columns, "data": rows, "dtypes": {name: "float" if name in rates else "int" for name in columns if name not in texts}, "formats": {name: "0.0%" for name in rates}}

def build_tables(raw, class_pairs, snapshot=None, now=None):
    now = int(time.time()) if now is None else now
    term_ids = {int(cid): int(tid) for cid, tid in class_pairs}
    current_classes = {int(c["classId"]): c for c in (snapshot or {}).get("classes", [])}
    by_class = {int(b["classId"]): b for b in raw}
    output, period_weeks = [], {}
    for class_id, block in by_class.items():
        teacher = str(block.get("info", {}).get("teacherName") or "").split("-C")[0]
        if block.get("excluded") or teacher == "薛超" or not teacher or (snapshot is not None and class_id not in current_classes):
            continue
        pairs = lesson_pairs(block)
        detail_courses = {int(i.get("course_id") or 0) for i in block.get("items", [])}
        weeks = [week_start(int(second["unlock_time"])) for _, second in pairs if 0 < int(second.get("unlock_time") or 0) <= now and int(second["course_id"]) in detail_courses]
        if not weeks:
            continue
        if class_id in current_classes:
            current_week = current_classes[class_id]["currentWeek"].removesuffix("周")
            start = int(datetime.strptime(current_week, "%Y-%m-%d").replace(tzinfo=CN).timestamp())
        else:
            start = max(weeks)
            current_week = datetime.fromtimestamp(start, CN).strftime("%Y-%m-%d")
        period_weeks[str(class_id)] = current_week
        info = block.get("info", {})
        for first, second in pairs:
            unlock = int(second.get("unlock_time") or 0)
            if not start <= unlock < start + 7 * 86400:
                continue
            metrics = period_metrics({**block, "lessons": [first, second]}, start, start + 7 * 86400, now)
            first_ids = {str(i["user_id"]) for i in block.get("items", []) if i.get("user_id") and int(i.get("course_id") or 0) == int(first["course_id"]) and i.get("is_open")}
            even_ids = {str(i["user_id"]) for i in block.get("items", []) if i.get("user_id") and int(i.get("course_id") or 0) == int(second["course_id"])}
            pending = bool(metrics.get("missingLiveBoards") or metrics.get("detailLiveFallbacks"))
            output.append([term_ids.get(class_id, int(block.get("termId") or 0)), info.get("termName", ""), teacher, class_id, info.get("className", ""), int(second["course_number"]), second.get("course_name", ""), first.get("course_name", ""),
                metrics["arrivalExpected"], metrics["arrivalAttend"], rate(metrics["arrivalAttend"], metrics["arrivalExpected"]),
                None if pending else metrics["liveExpected"], None if pending else metrics["liveAttend"], None if pending else rate(metrics["liveAttend"], metrics["liveExpected"]),
                metrics["evenExpected"], metrics["evenDone"], metrics["arrivedIncomplete"], len(even_ids - first_ids), metrics["evenExpected"] - metrics["evenDone"], rate(metrics["evenDone"], metrics["evenExpected"])])
    output.sort(key=lambda r: (r[0], r[2], r[3], r[5]))
    groups = defaultdict(list)
    for row in output:
        groups[(row[0], row[2])].append(row)
    overview = []
    for (term, teacher), rows in groups.items():
        ae, ad = sum(r[8] for r in rows), sum(r[9] for r in rows)
        fe, fd = sum(r[14] for r in rows), sum(r[15] for r in rows)
        pending = any(r[11] is None for r in rows)
        le, ld = sum(r[11] or 0 for r in rows), sum(r[12] or 0 for r in rows)
        overview.append([term, teacher, len({r[3] for r in rows}), ae, ad, rate(ad, ae), None if pending else le, None if pending else ld, None if pending else rate(ld, le), fe, fd, sum(r[16] for r in rows), fe - fd, rate(fd, fe)])
    overview.sort(key=lambda r: (r[0], -r[13], -(r[8] or 0), r[1]))
    return {"metricContract": METRICS_CONTRACT_VERSION, "classes": len(period_weeks), "sourceClasses": len(by_class), "classPeriodWeeks": period_weeks, "sheets": {
        "组内概览": make_table(OVERVIEW_COLUMNS, overview, {"老师"}, {"到课率", "直播上座率", "偶数课完课率"}),
        "班级课次看板": make_table(CLASS_COLUMNS, output, {"课期", "老师", "班级", "偶数课课程名称", "配对第一节课"}, {"到课率", "直播上座率", "完课率"})}}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--raw-file", default="group-lessons-raw.json")
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    by_id = {}
    for filename in args.raw_file.split(","):
        for block in json.loads((args.data_dir / filename).read_text(encoding="utf-8")):
            by_id[int(block["classId"])] = block
    snapshot_path = args.snapshot or args.data_dir.parent / "dashboard-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.exists() else None
    result = build_tables(list(by_id.values()), json.loads(args.classes.read_text(encoding="utf-8")), snapshot)
    target = args.data_dir / "group-dashboard-tables.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    print(json.dumps({"classes": result["classes"], "rows": {key: len(value["data"]) for key, value in result["sheets"].items()}}, ensure_ascii=False))

if __name__ == "__main__":
    main()
