"""Pure teaching metrics shared by snapshots, class tables and exports.

Arrival and completion use their corresponding course-detail population.
Verified room lists describe live attendance and never filter completion.
"""

METRICS_CONTRACT_VERSION = "course-detail-v1"


def course_detail_rows(block, lesson):
    """One row per learner, preserving positive statuses across branches."""
    course_id = int(lesson.get("course_id") or 0)
    merged = {}
    for row in block.get("items", []):
        uid = str(row.get("user_id") or "")
        if not uid or int(row.get("course_id") or 0) != course_id:
            continue
        previous = merged.get(uid)
        if previous is None:
            merged[uid] = dict(row)
            continue
        preferred = previous if previous.get("is_finish") else row if row.get("is_finish") or row.get("is_open") else previous
        combined = {**previous, **preferred}
        for flag in ("is_open", "is_finish", "live_course"):
            combined[flag] = bool(previous.get(flag) or row.get(flag))
        for key in ("watch_time", "watch_process"):
            combined[key] = max(float(previous.get(key) or 0), float(row.get(key) or 0))
        merged[uid] = combined
    return list(merged.values())


def lesson_pairs(block):
    """Pair lessons by actual unlock time, allowing inserted course numbers."""
    groups = {}
    for lesson in block.get("lessons", []):
        number = int(lesson.get("course_number") or 0)
        unlock = int(lesson.get("unlock_time") or 0)
        if number <= 0 or unlock <= 0 or "赛考精讲" in str(lesson.get("course_name") or ""):
            continue
        groups.setdefault(unlock, []).append(lesson)
    board_numbers = {int(key) for key in (block.get("liveAttendance") or {}) if str(key).isdigit()}
    pairs = []
    for _unlock, lessons in sorted(groups.items()):
        ordered = sorted(lessons, key=lambda item: (int(item.get("course_number") or 0), int(item.get("course_id") or 0)))
        first = next((item for item in ordered if int(item.get("course_number") or 0) in board_numbers), None)
        if first is not None:
            later = [item for item in ordered if int(item.get("course_number") or 0) > int(first.get("course_number") or 0)]
            second = later[0] if later else None
        else:
            first, second = (ordered[0], ordered[1]) if len(ordered) >= 2 else (None, None)
        if first is not None and second is not None:
            pairs.append((first, second))
    return pairs


def period_metrics(block, start, end, now, allow_detail_live=False):
    result = {"arrivalExpected": 0, "arrivalAttend": 0, "liveExpected": 0, "liveAttend": 0, "replayAttend": 0, "evenExpected": 0, "evenDone": 0, "arrivedIncomplete": 0, "missingLiveBoards": 0, "detailLiveFallbacks": 0, "incompleteIds": set(), "arrivedIncompleteIds": set(), "liveExpectedIds": set(), "liveAttendIds": set(), "liveAbsentIds": set(), "replayIds": set(), "latestOpenedTime": 0}
    for live_lesson, completion_lesson in lesson_pairs(block):
        live_number = int(live_lesson.get("course_number") or 0)
        even_rows = course_detail_rows(block, completion_lesson)
        live_rows = course_detail_rows(block, live_lesson)
        even_time = int(completion_lesson.get("unlock_time") or 0)
        live_time = int(live_lesson.get("unlock_time") or 0)
        pair_open = start <= even_time < end and even_time <= now
        if not pair_open:
            continue
        finish_roster = {str(row["user_id"]) for row in even_rows}
        arrival_roster = {str(row["user_id"]) for row in live_rows}
        finished_ids = {str(row["user_id"]) for row in even_rows if row.get("is_finish")}
        first_arrived_ids = {str(row["user_id"]) for row in live_rows if row.get("is_open")}
        arrived_incomplete = (first_arrived_ids & finish_roster) - finished_ids
        result["latestOpenedTime"] = max(result["latestOpenedTime"], even_time)
        result["evenExpected"] += len(finish_roster)
        result["evenDone"] += len(finished_ids)
        result["arrivedIncomplete"] += len(arrived_incomplete)
        result["incompleteIds"].update(finish_roster - finished_ids)
        result["arrivedIncompleteIds"].update(arrived_incomplete)
        if live_time > now:
            continue
        result["arrivalExpected"] += len(arrival_roster)
        result["arrivalAttend"] += len(first_arrived_ids)
        result["latestOpenedTime"] = max(result["latestOpenedTime"], live_time)
        board = (block.get("liveAttendance") or {}).get(str(live_number)) or (block.get("liveAttendance") or {}).get(live_number)
        if not board:
            if not allow_detail_live:
                result["missingLiveBoards"] += 1
                continue
            expected_ids = arrival_roster
            attended_ids = {str(row["user_id"]) for row in live_rows if row.get("live_course")}
            result["detailLiveFallbacks"] += 1
        else:
            expected_ids = {str(uid) for uid in board.get("expectedIds", []) if uid is not None and str(uid)}
            attended_ids = {str(uid) for uid in board.get("attendedIds", [])} & expected_ids
        result["liveExpected"] += len(expected_ids)
        result["liveAttend"] += len(attended_ids)
        result["liveExpectedIds"].update(expected_ids)
        result["liveAttendIds"].update(attended_ids)
        result["liveAbsentIds"].update(expected_ids - attended_ids)
        replay_ids = {str(row["user_id"]) for row in live_rows if str(row["user_id"]) in expected_ids - attended_ids and (float(row.get("watch_time") or 0) > 0 or float(row.get("watch_process") or 0) > 0)}
        result["replayAttend"] += len(replay_ids)
        result["replayIds"].update(replay_ids)
    return result
