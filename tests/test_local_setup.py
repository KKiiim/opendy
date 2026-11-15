import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

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
from run_local import create_app
path = Path(sys.argv[1])
app = create_app(path)
assert not app.debug
assert app.config["SECRET_KEY"] != "exam-master-local"
client = app.test_client()
assert client.get("/login").status_code == 200
assert client.get("/login", base_url="http://evil.example").status_code == 400
with sqlite3.connect(path / "database.db") as conn:
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
""", directory],
                cwd=ROOT, env=environment, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
