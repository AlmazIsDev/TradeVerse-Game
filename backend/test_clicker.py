import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from clicker import (
    DEFAULT_CONFIG,
    case_odds,
    component_case_odds,
    crypto_reward,
    _hardware_reward_doc,
    view,
)


def test_view_uses_wallet_clicks_instead_of_historical_progress():
    result = view({"clicks": 999, "multiplier": 2}, DEFAULT_CONFIG, wallet_clicks=17)
    assert result["clicks"] == 17


def test_case_odds_are_exposed_as_percentages():
    odds = case_odds("basic")
    assert odds == [
        {"type": "crypto", "chance": 66.67},
        {"type": "coolant", "chance": 16.67},
        {"type": "sunny_cottage", "chance": 16.67},
    ]


def test_component_case_odds_are_uniform_for_actual_pool():
    odds = component_case_odds("gpu", [{"id": "g1", "name": "GPU 1", "category": "gpu"}, {"id": "g2", "name": "GPU 2", "category": "gpu"}])
    assert odds == [
        {"type": "component", "itemId": "g1", "name": "GPU 1", "chance": 50.0},
        {"type": "component", "itemId": "g2", "name": "GPU 2", "chance": 50.0},
    ]


def test_crypto_reward_contains_symbol_name_and_amount():
    reward = crypto_reward({"symbol": "BTC", "name": "Bitcoin"}, 3)
    assert reward == {
        "type": "crypto",
        "title": "Bitcoin",
        "symbol": "BTC",
        "amount": 3,
    }


def test_hardware_reward_keeps_real_catalog_price():
    reward = _hardware_reward_doc("u1", {
        "id": "gpu-1",
        "category": "gpu",
        "name": "GPU",
        "base_price": 125000,
        "specs": {},
    })
    assert reward["purchase_price"] == 125000
