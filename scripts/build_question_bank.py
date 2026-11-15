"""Build a local question database from the versioned paper files."""
import argparse
from contextlib import closing
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "data" / "papers"
FIELDS = ("id", "stem", "answer", "difficulty", "qtype", "category", "options", "created_at", "explanation")


def load_questions(directory: Path) -> list[dict]:
    files = sorted(directory.glob("*.json"))
    if not files:
        raise ValueError(f"No paper JSON files found in {directory}")
    upstream = ROOT / "exam-master"
    if not (upstream / "db.py").is_file():
        raise RuntimeError("Upstream missing. Run: git submodule update --init")
    if str(upstream) not in sys.path:
        sys.path.insert(0, str(upstream))
    question_db = importlib.import_module("db")
    rows = []
    seen_ids = set()
    seen_categories = set()
    for path in files:
        with path.open(encoding="utf-8") as source:
            paper = json.load(source)
        if not isinstance(paper, list) or not paper:
            raise ValueError(f"{path}: a paper must contain a nonempty question list")
        categories = set()
        for number, row in enumerate(paper, 1):
            if not isinstance(row, dict) or set(row) != set(FIELDS):
                raise ValueError(f"{path}: question {number} has unexpected fields")
            for key in FIELDS:
                if key != "options" and not isinstance(row[key], str):
                    raise ValueError(f"{path}: question {number} field {key} must be a string")
            if any(not row[key].strip() for key in ("id", "stem", "answer", "qtype", "category")):
                raise ValueError(f"{path}: question {number} is missing required text")
            if row["qtype"] not in question_db.TYPES:
                raise ValueError(f"{path}: question {number} has an unsupported question type")
            options = row["options"]
            if not isinstance(options, dict) or any(
                key not in {"A", "B", "C", "D", "E"} or not isinstance(value, str) or not value.strip()
                for key, value in options.items()
            ):
                raise ValueError(f"{path}: question {number} has invalid options")
            issue = question_db.unpack(dict(row, options=json.dumps(options, ensure_ascii=False)))["issue"]
            if issue:
                raise ValueError(f"{path}: question {number}: {issue}")
            if row["id"] in seen_ids:
                raise ValueError(f"{path}: duplicate question ID {row['id']}")
            seen_ids.add(row["id"])
            categories.add(row["category"])
            rows.append(row)
        if len(categories) != 1 or categories & seen_categories:
            raise ValueError(f"{path}: each paper must have a unique category")
        seen_categories.update(categories)
    return rows


def build_database(rows: list[dict], destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        if not destination.is_file():
            raise ValueError(f"Destination is not a file: {destination}")
        return False
    descriptor, temporary = tempfile.mkstemp(prefix=".question-bank-", suffix=".db", dir=destination.parent)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute(
                "CREATE TABLE questions (id TEXT PRIMARY KEY, stem TEXT NOT NULL, answer TEXT NOT NULL, "
                "difficulty TEXT, qtype TEXT, category TEXT, options TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP, explanation TEXT NOT NULL DEFAULT '')"
            )
            db.executemany(
                "INSERT INTO questions (id,stem,answer,difficulty,qtype,category,options,created_at,explanation) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (tuple(json.dumps(row[key], ensure_ascii=False) if key == "options" else row[key]
                       for key in FIELDS) for row in rows),
            )
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Question database integrity check failed")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if not destination.is_file():
                raise
            return False
        return True
    finally:
        Path(temporary).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "guide-exam" / "database.db")
    args = parser.parse_args()
    os.umask(0o077)
    if args.output.exists():
        if not args.output.is_file():
            raise ValueError(f"Destination is not a file: {args.output}")
        print(f"Existing database preserved: {args.output}")
        return
    rows = load_questions(PAPERS)
    if build_database(rows, args.output):
        print(f"Created {args.output} with {len(rows)} questions")
    else:
        print(f"Existing database preserved: {args.output}")


if __name__ == "__main__":
    main()
