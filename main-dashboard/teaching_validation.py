"""Reject divergent teaching outputs before the first workbook mutation."""
from __future__ import annotations

import math
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

COUNTS = ("arrivalExpected", "arrivalAttend", "liveExpected", "liveAttend", "evenExpected", "evenDone", "arrivedIncomplete")
RATES = (("arrivalRate", "arrivalAttend", "arrivalExpected"), ("liveRate", "liveAttend", "liveExpected"), ("finishRate", "evenDone", "evenExpected"))
TABLE_COUNTS = {
    "第一节课应到人数": "arrivalExpected", "第一节课到课人数": "arrivalAttend",
    "直播应到人数": "liveExpected", "直播上座人数": "liveAttend",
    "应完课次数": "evenExpected", "已完课次数": "evenDone", "到课未完课次数": "arrivedIncomplete",
}


def fail(message):
    raise RuntimeError("教学数据写入前校验失败：" + message)


def check_metrics(metrics, label):
    for key in COUNTS:
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            fail(f"{label} {key} 不是非负整数")
    for rate, numerator, denominator in RATES:
        if metrics[numerator] > metrics[denominator]:
            fail(f"{label} {numerator} 超过对应分母")
        if rate == "liveRate" and metrics.get("livePending"):
            if metrics.get(rate) is not None:
                fail(f"{label} 待核实直播被写成有效率")
            continue
        expected = metrics[numerator] / metrics[denominator] if metrics[denominator] else 0
        actual = metrics.get(rate)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or not math.isclose(actual, expected, abs_tol=1e-10):
            fail(f"{label} {rate} 与分子分母不一致")
    # Different source populations are legitimate. Never equate all denominators.


def validate_teaching_outputs(raw, snapshot, dashboard, export, now=None):
    """Recompute class periods and compare the console, class sheet and totals."""
    from teaching_metrics import lesson_pairs, period_metrics
    from get_dashboard_snapshot import course_package, eligible_block, previous_opened_week, teacher_name, week_start

    now = int(time.time()) if now is None else int(now)
    blocks = {int(block["classId"]): block for block in raw}
    if len(blocks) != len(raw):
        fail("CRM 存在重复班级")
    classes = snapshot.get("classes", [])
    class_map = {int(row["classId"]): row for row in classes}
    eligible = {cid: block for cid, block in blocks.items() if eligible_block(block, now) and teacher_name(block.get("info", {}).get("teacherName"))}
    cohort_weeks, cohort_keys, opened_weeks = {}, {}, set()
    for cid, block in eligible.items():
        first_unlock = min(int(lesson.get("unlock_time") or 0) for lesson in block["lessons"] if int(lesson.get("unlock_time") or 0) > 0)
        cohort_key = (course_package(block), week_start(first_unlock))
        cohort_keys[cid] = cohort_key
        populated = {int(item.get("course_id") or 0) for item in block.get("items", [])}
        weeks = {week_start(int(second["unlock_time"])) for _, second in lesson_pairs(block) if 0 < int(second.get("unlock_time") or 0) <= now and int(second.get("course_id") or 0) in populated}
        cohort_weeks.setdefault(cohort_key, set()).update(weeks)
        opened_weeks.update(weeks)
    if not opened_weeks:
        fail("原始数据没有已开课课程")
    expected_starts = {cid: max(cohort_weeks[cohort_keys[cid]] or opened_weeks) for cid in eligible}
    expected_classes = {cid for cid, block in eligible.items() if period_metrics(block, expected_starts[cid], expected_starts[cid] + 7 * 86400, now)["latestOpenedTime"] > 0}
    if len(class_map) != len(classes) or set(class_map) != expected_classes:
        fail("快照班级范围与本次 CRM 班级范围不一致")
    zone = timezone(timedelta(hours=8))
    for cid, row in class_map.items():
        start = int(datetime.strptime(str(row["currentWeek"])[:10], "%Y-%m-%d").replace(tzinfo=zone).timestamp())
        if start != expected_starts[cid]:
            fail(f"班级 {cid} 统计周与原始开课周期不一致")
        metrics = row["current"]
        actual = period_metrics(blocks[cid], start, start + 7 * 86400, now, allow_detail_live=bool(metrics.get("detailLiveFallbacks")))
        check_metrics(metrics, f"班级 {cid}")
        for key in COUNTS:
            if actual[key] != metrics[key]:
                fail(f"班级 {cid} {key} 与原始课次不一致")
        for public_key, internal_key in (("incompleteList", "incompleteIds"), ("liveAbsentList", "liveAbsentIds")):
            ids = [str(item["id"]) for item in metrics.get(public_key, [])]
            if len(ids) != len(set(ids)) or set(ids) != actual[internal_key]:
                fail(f"班级 {cid} {public_key} 与原始名单不一致")

    teacher_keys = set()
    for row in snapshot.get("rows", []):
        key = (row["teacher"], row["cohort"])
        if key in teacher_keys:
            fail("重复的老师课期汇总")
        teacher_keys.add(key)
        members = [item for item in classes if (item["teacher"], item["cohort"]) == key]
        check_metrics(row["current"], f"老师 {key[0]}")
        for count in COUNTS:
            if row["current"][count] != sum(item["current"][count] for item in members):
                fail(f"老师 {key[0]} {count} 与班级合计不一致")
        if "previous" in row:
            previous = row["previous"]
            check_metrics(previous, f"老师 {key[0]} 上期")
            previous_totals = {count: 0 for count in COUNTS}
            matched_raw = False
            for cid, block in eligible.items():
                package, cohort_start = cohort_keys[cid]
                cohort = package + " · " + datetime.fromtimestamp(cohort_start, zone).strftime("%Y-%m-%d周")
                if (teacher_name(block.get("info", {}).get("teacherName")), cohort) != key:
                    continue
                matched_raw = True
                # Current-period class rows omit future slots. Their previous
                # periods still contribute to the teacher's historical total.
                weeks = cohort_weeks[cohort_keys[cid]] or {expected_starts[cid]}
                previous_start = previous_opened_week(weeks, expected_starts[cid])
                raw_previous = period_metrics(block, previous_start, previous_start + 7 * 86400, now, allow_detail_live=bool(previous.get("detailLiveFallbacks")))
                for count in COUNTS:
                    previous_totals[count] += raw_previous[count]
            if not matched_raw:
                fail(f"老师 {key[0]} 上期缺少对应原始课期")
            for count in COUNTS:
                if previous[count] != previous_totals[count]:
                    fail(f"老师 {key[0]} 上期 {count} 与原始班级合计不一致")
    if not {(row["teacher"], row["cohort"]) for row in classes}.issubset(teacher_keys):
        fail("老师课期汇总范围不完整")
    if {teacher for teacher, _ in teacher_keys} != {teacher_name(block.get("info", {}).get("teacherName")) for block in eligible.values()}:
        fail("老师汇总范围与原始班级不一致")

    table = dashboard.get("sheets", {}).get("班级课次看板")
    if not table:
        fail("缺少班级课次看板")
    columns = table.get("columns", [])
    period_weeks = dashboard.get("classPeriodWeeks")
    if period_weeks is not None:
        expected_weeks = {str(cid): str(row["currentWeek"])[:10] for cid, row in class_map.items()}
        if period_weeks != expected_weeks:
            fail("班级课次表统计周与快照不一致")
    required = ["班级ID", *TABLE_COUNTS]
    if any(key not in columns for key in required):
        fail("班级课次看板字段不完整")
    by_class = {}
    for values in table.get("data", []):
        if len(values) != len(columns):
            fail("班级课次看板列数不一致")
        cid = int(values[columns.index("班级ID")])
        if cid not in class_map:
            fail(f"班级表包含范围外班级 {cid}")
        for rate, numerator, denominator in (("到课率", "第一节课到课人数", "第一节课应到人数"), ("直播上座率", "直播上座人数", "直播应到人数"), ("完课率", "已完课次数", "应完课次数")):
            if rate not in columns:
                continue
            if rate == "直播上座率" and class_map[cid]["current"].get("livePending"):
                if values[columns.index(rate)] not in (None, ""):
                    fail(f"班级表 {cid} 待核实直播被写成有效率")
                continue
            done, total = values[columns.index(numerator)], values[columns.index(denominator)]
            actual_rate = values[columns.index(rate)]
            if not isinstance(actual_rate, (int, float)) or not isinstance(done, (int, float)) or not isinstance(total, (int, float)):
                fail(f"班级表 {cid} {rate} 数值无效")
            if not math.isclose(actual_rate, done / total if total else 0, abs_tol=1e-10):
                fail(f"班级表 {cid} {rate} 与分子分母不一致")
        target = by_class.setdefault(cid, {key: 0 for key in TABLE_COUNTS.values()})
        for header, key in TABLE_COUNTS.items():
            value = values[columns.index(header)]
            if key.startswith("live") and class_map[cid]["current"].get("livePending") and value in (None, ""):
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                fail(f"班级表 {cid} {header} 不是非负整数")
            target[key] += value
    if set(by_class) != set(class_map):
        fail("班级课次表缺少快照班级")
    for cid, counts in by_class.items():
        for key, value in counts.items():
            if key.startswith("live") and class_map[cid]["current"].get("livePending"):
                continue
            if value != class_map[cid]["current"][key]:
                fail(f"班级表 {cid} {key} 与主看板不一致")
    from run_dashboard_update import validate_abnormal_summary
    validate_abnormal_summary(export["tables"]["异常学员"], snapshot)


@contextmanager
def preserve_generated_outputs(root):
    """Restore previous local outputs if candidate generation/validation fails."""
    root = Path(root)
    paths = [root / "dashboard-snapshot.json", root / "run-data/group-dashboard-tables.json", root / "run-data/exception-export-tables.json"]
    originals = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        yield
    except BaseException:
        for path, previous in originals.items():
            if previous is None:
                path.unlink(missing_ok=True)
                continue
            temporary = path.with_name(path.name + ".restore-" + uuid.uuid4().hex)
            temporary.write_bytes(previous)
            os.replace(temporary, path)
        raise
