"""Local-only, empty-bank launcher for the tour guide exam workspace."""
import argparse
import importlib
import os
from pathlib import Path
import secrets
import sys

from flask import Flask

ROOT = Path(__file__).resolve().parent


def load_secret(data_dir: Path) -> str:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    data_dir.chmod(0o700)
    path = data_dir / "session.key"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(secrets.token_hex(32))
    path.chmod(0o600)
    value = path.read_text(encoding="ascii").strip()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"Invalid session key file: {path}. Restore a valid backup.")
    return value


def create_app(data_dir: Path) -> Flask:
    upstream = ROOT / "exam-master"
    if not (upstream / "app.py").is_file():
        raise RuntimeError("Upstream missing. Run: git submodule update --init")
    os.umask(0o077)
    os.environ["SECRET_KEY"] = load_secret(data_dir)
    os.environ["EXAM_DATABASE"] = str(data_dir / "database.db")
    os.environ["EXAM_SEED_CSV"] = ""
    sys.path.insert(0, str(upstream))
    # Upstream initializes its database during import, so configure it first.
    app = importlib.import_module("app").app
    app.config.update(
        DEBUG=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        TRUSTED_HOSTS=["127.0.0.1", "localhost"],
    )
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=32220)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    app = create_app(ROOT / ".local" / "guide-exam")
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
