import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Tests must never depend on a real API key: force the offline fake model.
os.environ.pop("OPENAI_API_KEY", None)

from scripts.build_demo_db import build  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def demo_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("data") / "demo.db"
    build(str(db_path))
    os.environ["SQL_ASSISTANT_DB_PATH"] = str(db_path)
    return str(db_path)


@pytest.fixture()
def client(demo_db):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
