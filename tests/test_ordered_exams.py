from contextlib import closing
import csv
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from scripts.build_question_bank import build_database, load_questions
from scripts.ordered_exams import question_order_key
from run_local import ROOT, create_app


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def compact(text):
    return "".join(text.split())


class OrderedExamTest(unittest.TestCase):
    category = "雷大大押题卷26 / 第1卷 / 科目一二"

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.questions = load_questions(ROOT / "data" / "papers")
        build_database(cls.questions, cls.directory / "database.db")
        cls.app = create_app(cls.directory)
        cls.app.config["TESTING"] = True
        client = cls.app.test_client()
        response = client.post("/register", data={
            "username": "order-test", "password": "temporary-test-password",
            "confirm_password": "temporary-test-password",
        })
        if response.status_code != 302:
            raise RuntimeError("Failed to register test user")

    def setUp(self):
        self.client = self.app.test_client()
        response = self.client.post("/login", data={
            "username": "order-test", "password": "temporary-test-password",
        })
        self.assertEqual(response.status_code, 302)

    def start_exam(self, form, endpoint="/start_exam"):
        response = self.client.post(endpoint, data=form)
        self.assertEqual(response.status_code, 302)
        self.assertRegex(response.location, r"/exam/\d+$")
        with closing(sqlite3.connect(self.directory / "database.db")) as db:
            row = db.execute(
                "SELECT question_ids, paper, mode, duration FROM exam_sessions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return response, json.loads(row[0]), json.loads(row[1]), row[2], row[3]

    def test_selected_paper_starts_at_first_question(self):
        with mock.patch.object(sys.modules["app"].random, "sample", side_effect=AssertionError("random sample")):
            response, ids, paper, mode, duration = self.start_exam({
                "mode": "exam", "category": self.category, "question_count": "3",
            })
        self.assertEqual([int(item.rsplit("-", 1)[1]) for item in ids], [1, 2, 3])
        self.assertEqual([question["id"] for question in paper], ids)
        self.assertEqual((mode, duration), ("exam", 0))
        page = PageText()
        page.feed(self.client.get(response.location).get_data(as_text=True))
        text = compact("".join(page.parts))
        positions = [text.find(compact(question["stem"])) for question in paper]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(positions, sorted(positions))

        result = self.client.post(
            response.location,
            data={f"answer_{question['id']}": question["answer"] for question in paper},
            follow_redirects=True,
        )
        self.assertEqual(result.status_code, 200)
        with closing(sqlite3.connect(self.directory / "database.db")) as db:
            history = db.execute(
                "SELECT question_id, user_answer, correct FROM history WHERE question_id IN (?, ?, ?)",
                ids,
            ).fetchall()
        self.assertEqual(
            set(history), {(question["id"], question["answer"], 1) for question in paper}
        )

    def test_order_respects_type_filter_and_missing_numbers(self):
        _, ids, _, _, _ = self.start_exam({
            "category": self.category, "type": "单选题", "question_count": "3",
        })
        self.assertEqual([int(item.rsplit("-", 1)[1]) for item in ids], [41, 42, 43])
        _, ids, _, _, _ = self.start_exam({"category": self.category, "question_count": "999"})
        expected = sorted(
            (row for row in self.questions if row["category"] == self.category),
            key=lambda row: int(row["id"].rsplit("-", 1)[1]),
        )
        self.assertEqual(ids, [row["id"] for row in expected])

    def test_numeric_identifiers_are_sorted_numerically(self):
        questions = [{"id": number, "stem": "未编号题干"} for number in ("10", "2", "1")]
        self.assertEqual([row["id"] for row in sorted(questions, key=question_order_key)], ["1", "2", "10"])

    def test_timed_modes_keep_paper_order(self):
        for endpoint, mode in (("/start_exam", "timed"), ("/start_timed_mode", "exam")):
            with self.subTest(endpoint=endpoint):
                _, ids, _, stored_mode, duration = self.start_exam({
                    "category": self.category, "question_count": "2", "mode": mode, "duration": "7",
                }, endpoint)
                self.assertEqual([int(item.rsplit("-", 1)[1]) for item in ids], [1, 2])
                self.assertEqual((stored_mode, duration), ("timed", 420))

    def test_all_categories_still_use_upstream_random_sampling(self):
        chosen = []

        def reverse_sample(population, count):
            selection = list(reversed(population))[:count]
            chosen.extend(row["id"] for row in selection)
            return selection

        with mock.patch.object(sys.modules["app"].random, "sample", side_effect=reverse_sample) as sample:
            _, ids, _, _, _ = self.start_exam({"category": "", "question_count": "3"})
        sample.assert_called_once()
        self.assertEqual(ids, chosen)

    def test_invalid_or_empty_selection_does_not_create_exam(self):
        with closing(sqlite3.connect(self.directory / "database.db")) as db:
            before = db.execute("SELECT COUNT(*) FROM exam_sessions").fetchone()[0]
        for form in ({"category": self.category, "question_count": "0"},
                     {"category": "不存在的分类", "question_count": "3"}):
            with self.subTest(form=form):
                response = self.client.post("/start_exam", data=form)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.location.endswith("/modes"))
        with closing(sqlite3.connect(self.directory / "database.db")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM exam_sessions").fetchone()[0], before)

    def test_manual_wrong_marks_merge_with_history_without_writing_it(self):
        manual_ids = set(self.app.config["MANUAL_WRONG_IDS"])
        manual_id = next(iter(manual_ids))
        other_id = next(row["id"] for row in self.questions if row["id"] not in manual_ids)
        with closing(sqlite3.connect(self.directory / "database.db")) as db, db:
            user_id = db.execute("SELECT id FROM users WHERE username=?", ("order-test",)).fetchone()[0]
            inserted = [
                db.execute(
                    "INSERT INTO history (user_id, question_id, user_answer, correct) VALUES (?, ?, ?, 0)",
                    (user_id, qid, "wrong"),
                ).lastrowid
                for qid in (manual_id, other_id)
            ]
        try:
            with closing(sqlite3.connect(self.directory / "database.db")) as db:
                before = db.execute("SELECT * FROM history ORDER BY id").fetchall()
                history_ids = {
                    row[0] for row in db.execute(
                        "SELECT question_id FROM history WHERE user_id=? AND correct=0", (user_id,)
                    )
                }
            expected = manual_ids | history_ids
            response = self.client.get("/questions/export", query_string={"scope": "wrong"})
            self.assertEqual(response.status_code, 200)
            rows = csv.DictReader(io.StringIO(response.data.decode("utf-8-sig")))
            self.assertEqual({row["题号"] for row in rows}, expected)
            with mock.patch.dict(self.app.config, {"MANUAL_WRONG_IDS": []}):
                original = self.client.get("/questions/export", query_string={"scope": "wrong"})
                rows = csv.DictReader(io.StringIO(original.data.decode("utf-8-sig")))
                self.assertEqual({row["题号"] for row in rows}, history_ids)
            filtered = self.client.get(
                "/questions/export", query_string={"scope": "wrong", "type": "判断题"}
            )
            rows = csv.DictReader(io.StringIO(filtered.data.decode("utf-8-sig")))
            self.assertEqual(
                {row["题号"] for row in rows},
                {row["id"] for row in self.questions if row["id"] in expected and row["qtype"] == "判断题"},
            )
            page = self.client.get("/wrong").get_data(as_text=True)
            self.assertIn(f"<span>{len(expected)}</span>", page)
            dashboard = self.client.get("/").get_data(as_text=True)
            self.assertRegex(dashboard, rf"(?s)待巩固错题.*?big-number\">{len(expected)}<span>题")
            practice = self.client.get("/practice/wrong", query_string={"search": manual_id})
            self.assertEqual(practice.status_code, 302)
            self.assertIn(manual_id, practice.location)
            with closing(sqlite3.connect(self.directory / "database.db")) as db:
                self.assertEqual(db.execute("SELECT * FROM history ORDER BY id").fetchall(), before)
        finally:
            with closing(sqlite3.connect(self.directory / "database.db")) as db, db:
                db.executemany("DELETE FROM history WHERE id=?", [(row_id,) for row_id in inserted])


if __name__ == "__main__":
    unittest.main()
