import os
import tempfile
import time
import uuid

# Must be set before any `app.*` import: settings and the DB bind at import time.
os.environ.setdefault("WASIGNAL_DATA_DIR", tempfile.mkdtemp(prefix="wasignal-test-"))
os.environ.setdefault("WASIGNAL_ENV", "dev")
os.environ.setdefault("WASIGNAL_SEED_DEMO", "1")
os.environ.setdefault("WASIGNAL_SCHEDULER", "0")
if os.environ.get("WASIGNAL_TEST_BACKEND") == "mongo":
    os.environ.setdefault("WASIGNAL_DB_BACKEND", "mongo")
    os.environ.setdefault("WASIGNAL_MONGOMOCK", "1")
    os.environ.setdefault("WASIGNAL_FAKEREDIS", "1")
os.environ.setdefault("WASIGNAL_LLM_PROVIDER", "echo")
os.environ.setdefault("WASIGNAL_CHANNEL", "stub")

import pytest  # noqa: E402

from app import repo  # noqa: E402
from app.seed import seed_demo  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _seed() -> None:
    seed_demo()


@pytest.fixture()
def account() -> dict:
    return repo.default_account(1)


@pytest.fixture()
def fresh_account() -> dict:
    """A clean tenant per test: no seeded agents can match unexpectedly."""
    phone = f"9{uuid.uuid4().int % 10**9:09d}"
    pid = repo.create_partner(phone, f"Test {phone[-4:]}")
    org = repo.create_org(pid, f"Test org {phone[-4:]}", f"test-{phone[-4:]}-{pid}")
    account_id = repo.create_account_full(
        int(org["id"]), pid, f"Test account {phone[-4:]}", "", "Asia/Kolkata", "active"
    )
    return repo.account_by_id(account_id)


@pytest.fixture()
def world(account: dict):
    rooms = repo.list_rooms(int(account["id"]))
    agents = repo.list_agents(int(account["id"]))
    return {"account": account, "rooms": rooms, "agents": agents}
