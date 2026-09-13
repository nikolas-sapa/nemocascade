import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from devtools.mock_server import MockState, create_server  # noqa: E402

TASKS = ROOT / "tasks" / "tasks.json"
TASKS_NEGATIVE = ROOT / "tasks" / "tasks_negative.json"

# Placeholder prices used to make cost math deterministic in tests.
TEST_CONFIG = {
    "ladder": ["nano", "super", "ultra"],
    "tiers": {
        "nano": {"model": None, "price_in_per_1m": 0.04, "price_out_per_1m": 0.16},
        "super": {"model": None, "price_in_per_1m": 0.40, "price_out_per_1m": 1.60},
        "ultra": {"model": None, "price_in_per_1m": 2.00, "price_out_per_1m": 8.00},
    },
}


@pytest.fixture()
def mock_base_url():
    state = MockState()
    server = create_server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    yield f"http://{host}:{port}", state
    server.shutdown()
    server.server_close()
