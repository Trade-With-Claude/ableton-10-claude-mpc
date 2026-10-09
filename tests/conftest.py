import pytest

from claude_mpc.client import LiveClient
from fake_live import FakeLive


@pytest.fixture
def fake_live():
    fl = FakeLive()
    yield fl
    fl.close()


@pytest.fixture
def client(fake_live):
    c = LiveClient(port=fake_live.port, timeout=2.0)
    yield c
    c.close()
