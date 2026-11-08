import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from clicker import (
    CASE_REWARD_WEIGHTS,
    DEFAULT_CONFIG,
    case_odds,
    component_case_odds,
    crypto_reward,
    _hardware_reward_doc,
    reward_asset_catalog,
    view,
)


def test_view_uses_wallet_clicks_instead_of_historical_progress():
    result = view({"clicks": 999, "multiplier": 2}, DEFAULT_CONFIG, wallet_clicks=17)
    assert result["clicks"] == 17


def test_case_odds_match_all_reward_weights():
    for case_id, weights in CASE_REWARD_WEIGHTS.items():
        assert case_odds(case_id) == [
            {"type": reward_type, "chance": round(weight / sum(weights.values()) * 100, 2)}
            for reward_type, weight in weights.items()
        ]


def test_asset_reward_cap_keeps_catalog_rewards_available():
    catalog = [
        {"type": "business", "slug": "coffee", "price": 6_000_000},
        {"type": "business", "slug": "cheap", "price": 60_000},
    ]
    assert reward_asset_catalog("business", catalog, 100_000)["slug"] == "cheap"
    assert reward_asset_catalog("business", catalog, 100_000) is not None


def test_asset_reward_without_cap_can_select_expensive_item():
    item = reward_asset_catalog("house", [{"type": "realestate", "slug": "villa", "price": 1_000_000}])
    assert item["slug"] == "villa"


# Existing catalog prices are intentionally scaled; the reward cap is applied
# to a reward budget, not to the displayed purchase price.


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
