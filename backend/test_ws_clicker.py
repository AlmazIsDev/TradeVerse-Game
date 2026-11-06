import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import clicker


def test_clicker_event_contains_current_wallet_state():
    event = clicker.clicker_event({"clicks": 42, "clickPower": 3})
    assert event == {"type": "clicker_balance", "clicks": 42, "clickPower": 3}
