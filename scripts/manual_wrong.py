"""Merge versioned paper-number marks into the existing wrong-question set."""
import json
from pathlib import Path
import re

from flask import before_render_template, g


def load_manual_wrong(path: Path, papers: Path) -> tuple[list[str], list[str]]:
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8") as source:
        marks = json.load(source)
    if not isinstance(marks, dict):
        raise ValueError(f"{path}: expected an object mapping paper files to question numbers")
    ids = []
    missing = []
    for filename, numbers in marks.items():
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".json"):
            raise ValueError(f"{path}: invalid paper filename {filename!r}")
        if not isinstance(numbers, list) or any(type(number) is not int or number < 1 for number in numbers):
            raise ValueError(f"{path}: {filename} must contain positive integer question numbers")
        if len(set(numbers)) != len(numbers):
            raise ValueError(f"{path}: {filename} contains duplicate question numbers")
        with (papers / filename).open(encoding="utf-8") as source:
            paper = json.load(source)
        if not isinstance(paper, list):
            raise ValueError(f"{papers / filename}: expected a question list")
        by_number = {}
        for question in paper:
            if not isinstance(question, dict) or not isinstance(question.get("id"), str):
                raise ValueError(f"{papers / filename}: question is missing its ID")
            match = re.fullmatch(r"guide-[0-9a-f]{16}-(\d+)", question["id"])
            if not match:
                raise ValueError(f"{papers / filename}: invalid question ID {question['id']!r}")
            number = int(match.group(1))
            if number in by_number:
                raise ValueError(f"{papers / filename}: duplicate question number {number}")
            by_number[number] = question["id"]
        for number in numbers:
            if number in by_number:
                ids.append(by_number[number])
            else:
                missing.append(f"{filename}:{number}")
    return ids, missing


def install_manual_wrong(upstream, path: Path, papers: Path) -> None:
    app = upstream.app
    ids, missing = load_manual_wrong(path, papers)
    app.config["MANUAL_WRONG_IDS"] = ids
    if missing:
        app.logger.warning("手动错题在试卷 JSON 中未找到：%s", ", ".join(missing))
    with app.app_context():
        present = {row["id"] for row in upstream.query(
            "SELECT id FROM questions WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(ids),)
        )}
    absent = [qid for qid in ids if qid not in present]
    if absent:
        app.logger.warning("手动错题中有 %d 题不在当前数据库中：%s", len(absent), ", ".join(absent))
    if app.extensions.get("opendy_manual_wrong"):
        return

    def wrong_clause():
        return (
            "(EXISTS (SELECT 1 FROM history h WHERE h.question_id=q.id AND h.user_id=? AND h.correct=0) "
            "OR q.id IN (SELECT value FROM json_each(?)))",
            [g.user["id"], json.dumps(app.config["MANUAL_WRONG_IDS"])],
        )

    original_filters = upstream.filters

    def filters(scope="all"):
        if scope != "wrong" or not app.config["MANUAL_WRONG_IDS"]:
            return original_filters(scope)
        values, where, params = original_filters()
        clause, extra = wrong_clause()
        return values, where + (" AND " if where else " WHERE ") + clause, params + extra

    upstream.filters = filters

    def update_dashboard(sender, template, context):
        if sender is app and template.name == "dashboard.html" and app.config["MANUAL_WRONG_IDS"]:
            clause, params = wrong_clause()
            context["stats"]["wrong"] = upstream.query(
                "SELECT COUNT(*) AS n FROM questions q WHERE " + clause, params, one=True
            )["n"]

    before_render_template.connect(update_dashboard, app, weak=False)
    app.extensions["opendy_manual_wrong"] = True
