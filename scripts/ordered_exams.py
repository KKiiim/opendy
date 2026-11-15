"""Use paper order when a specific question category is selected."""
from datetime import datetime
from functools import wraps
import json
import re

from flask import flash, g, redirect, request, session, url_for


def question_order_key(question: dict) -> tuple[int, int, str]:
    identifier = question["id"]
    match = re.fullmatch(r"guide-[0-9a-f]{16}-(\d+)", identifier)
    if not match:
        match = re.match(r"\s*(\d+)[.．、]", question["stem"])
    if match:
        return (0, int(match.group(1)), identifier)
    if identifier.isdecimal():
        return (0, int(identifier), identifier)
    return (1, 0, identifier)


def install_ordered_exams(upstream) -> None:
    app = upstream.app
    if app.extensions.get("opendy_ordered_exams"):
        return

    def wrap(original):
        @wraps(original)
        def start_exam():
            values, where, params = upstream.filters()
            if values["category"] in ("", "all"):
                return original()
            timed = request.endpoint == "start_timed_mode" or request.form.get("mode") == "timed"
            count = request.form.get("question_count", 10, type=int)
            duration = request.form.get("duration", 10, type=int) if timed else 0
            if count < 1 or (timed and duration < 1):
                flash("题量和限时需要大于 0。")
                return redirect(url_for("modes"))
            available = [upstream.unpack(row) for row in upstream.query(f"SELECT * FROM questions q {where}", params)]
            paper = sorted((row for row in available if not row["issue"]), key=question_order_key)[:count]
            if not paper:
                flash("当前条件下没有题目，请先添加题目或调整筛选。")
                return redirect(url_for("modes"))
            conn = upstream.get_db()
            with conn:
                exam_id = conn.execute(
                    "INSERT INTO exam_sessions (user_id, mode, question_ids, start_time, duration, paper) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (g.user["id"], "timed" if timed else "exam", json.dumps([row["id"] for row in paper]),
                     datetime.now().isoformat(timespec="seconds"), duration * 60,
                     json.dumps(paper, ensure_ascii=False)),
                ).lastrowid
            if exam_id is None:
                raise RuntimeError("Failed to create exam session")
            session["current_exam_id"] = exam_id
            return redirect(url_for("exam", exam_id=exam_id))

        return start_exam

    # Upstream has no selection-order hook, so replace only these endpoints.
    for endpoint in ("start_exam", "start_timed_mode"):
        app.view_functions[endpoint] = wrap(app.view_functions[endpoint])
    app.extensions["opendy_ordered_exams"] = True
