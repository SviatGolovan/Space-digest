import os
import sys
from pathlib import Path

os.environ["SPACEDIGEST_NO_MODEL_DOWNLOAD"] = "1"      # тесты не качают модели из сети

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"

from spacedigest.core.db import Database  # noqa: E402
from spacedigest.core.jobs import JobQueue, WorkerPool  # noqa: E402
from spacedigest.services.sources import SourceRepo  # noqa: E402


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.migrate()
    yield d
    d.close()


@pytest.fixture
def repo(db):
    return SourceRepo(db)


@pytest.fixture
def queue(db):
    return JobQueue(db)


@pytest.fixture
def pool(queue):
    return WorkerPool(queue, threads=1)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeResponse:
    def __init__(self, url, content=b"", status=200, headers=None):
        self.url, self.content, self.status_code = url, content, status
        self.headers = headers or {}

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")


class FakeSession:
    """Подменяет requests.Session: отдаёт заранее заданные ответы и запоминает запросы."""

    def __init__(self, routes):
        self.routes = routes          # url → FakeResponse | callable(headers) → FakeResponse
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        r = self.routes.get(url)
        if r is None:
            return FakeResponse(url, b"not found", 404)
        return r(headers or {}) if callable(r) else r
