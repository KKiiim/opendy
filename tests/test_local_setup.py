from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from scripts.build_question_bank import build_database, load_questions
from scripts.manual_wrong import load_manual_wrong
from run_local import ROOT, load_secret


class LocalSetupTest(unittest.TestCase):
    def test_secret_is_private_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data"
            first = load_secret(path)
            self.assertEqual(first, load_secret(path))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((path / "session.key").stat().st_mode), 0o600)

    def test_invalid_secret_fails_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "session.key").write_text("invalid", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "Invalid session key"):
                load_secret(path)
            self.assertEqual((path / "session.key").read_text(), "invalid")

    def test_empty_bank_and_local_host_restriction(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update(EXAM_SEED_CSV=str(ROOT / "exam-master" / "questions.csv"),
                               SECRET_KEY="exam-master-local", FLASK_DEBUG="1")
            result = subprocess.run(
                [sys.executable, "-c", """
import sqlite3
import sys
from pathlib import Path
from contextlib import closing
from run_local import create_app
path = Path(sys.argv[1])
app = create_app(path)
assert not app.debug
assert app.config["SECRET_KEY"] != "exam-master-local"
client = app.test_client()
assert client.get("/login").status_code == 200
assert client.get("/login", base_url="http://evil.example").status_code == 400
with closing(sqlite3.connect(path / "database.db")) as conn:
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
""", directory],
                cwd=ROOT, env=environment, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_packaged_bank_initializes_without_personal_data(self):
        questions = sorted(load_questions(ROOT / "data" / "papers"), key=lambda row: row["id"])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "database.db"
            self.assertTrue(build_database(questions, database))
            with closing(sqlite3.connect(database)) as conn:
                conn.row_factory = sqlite3.Row
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )}
                self.assertEqual(tables, {"questions"})
                rows = [dict(row) for row in conn.execute("SELECT * FROM questions ORDER BY id")]
                for row in rows:
                    row["options"] = json.loads(row["options"])
                self.assertEqual(rows, questions)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            result = subprocess.run(
                [sys.executable, "-c", """
import sys
from pathlib import Path
from run_local import create_app
app = create_app(Path(sys.argv[1]))
assert app.test_client().get("/login").status_code == 200
""", directory],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with closing(sqlite3.connect(database)) as conn:
                conn.row_factory = sqlite3.Row
                rows = [dict(row) for row in conn.execute("SELECT * FROM questions ORDER BY id")]
                for row in rows:
                    row["options"] = json.loads(row["options"])
                self.assertEqual(rows, questions)
                for table in ("users", "history", "favorites", "exam_sessions"):
                    self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_existing_database_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "database.db"
            database.write_bytes(b"existing database")
            self.assertFalse(build_database([], database))
            self.assertEqual(database.read_bytes(), b"existing database")

    def test_database_created_concurrently_is_not_overwritten(self):
        question = load_questions(ROOT / "data" / "papers")[0]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "database.db"

            def create_competing_database(source, destination):
                self.assertTrue(Path(source).is_file())
                Path(destination).write_bytes(b"concurrent database")
                raise FileExistsError(destination)

            with mock.patch("scripts.build_question_bank.os.link", side_effect=create_competing_database):
                self.assertFalse(build_database([question], database))
            self.assertEqual(database.read_bytes(), b"concurrent database")
            self.assertEqual(list(database.parent.glob(".question-bank-*.db")), [])

    def test_duplicate_question_id_is_rejected(self):
        question = load_questions(ROOT / "data" / "papers")[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps([question, question], ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate question ID"):
                load_questions(path.parent)

    def test_invalid_answer_is_rejected(self):
        question = dict(load_questions(ROOT / "data" / "papers")[0], answer="无效答案")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps([question], ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "判断题答案无效"):
                load_questions(path.parent)

    def test_manual_wrong_numbers_and_missing_questions(self):
        first = {3, 9, 10, 16, 18, 19, 21, 23, 24, 26, 28, 31, 37, 38}
        middle = {
            41, 42, 45, 51, 53, 54, 55, 56, 58, 59, 60, 63, 67, 68, 69, 71, 72,
            73, 74, 75, 76, 77, 78, 79, 81, 87, 89, 91, 94, 96, 99, 100, 104,
            105, 110, 114, 116, 117, 119, 120, 121, 122, 124, 127, 129,
        }
        last = set(range(131, 166)) - {138, 139, 141, 147, 157}
        ids, missing = load_manual_wrong(ROOT / "data" / "wrong-questions.json", ROOT / "data" / "papers")
        self.assertEqual(len(ids), 86)
        self.assertEqual({int(qid.rsplit("-", 1)[1]) for qid in ids}, (first | middle | last) - {75, 76, 77})
        self.assertEqual(missing, [f"leidadu-01-12.json:{number}" for number in (75, 76, 77)])

    def test_duplicate_manual_wrong_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.json"
            path.write_text('{"leidadu-01-12.json": [1, 1]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate question numbers"):
                load_manual_wrong(path, ROOT / "data" / "papers")

    def test_script_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "database.db"
            build = subprocess.run(
                [sys.executable, "scripts/build_question_bank.py", "--output", str(database)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
                    len(load_questions(ROOT / "data" / "papers")),
                )
            launcher = subprocess.run(
                [sys.executable, "run_local.py", "--help"],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(launcher.returncode, 0, launcher.stdout + launcher.stderr)
            self.assertIn("--port", launcher.stdout)

    def test_launcher_serves_login_from_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy2(ROOT / "run_local.py", root / "run_local.py")
            (root / "scripts").mkdir()
            for name in ("__init__.py", "ordered_exams.py", "manual_wrong.py"):
                shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
            (root / "exam-master").symlink_to(ROOT / "exam-master", target_is_directory=True)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen(
                [sys.executable, str(root / "run_local.py"), "--port", str(port)],
                cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            )
            try:
                opener = build_opener(ProxyHandler({}))
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        self.fail(f"Launcher exited: {process.stderr.read()}")
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/login", timeout=1) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn("登录", response.read().decode("utf-8"))
                        break
                    except HTTPError as error:
                        with error:
                            self.fail(f"Launcher returned HTTP {error.code}")
                    except URLError:
                        if time.monotonic() >= deadline:
                            self.fail("Launcher did not serve the login page within 10 seconds")
                        time.sleep(0.1)
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
