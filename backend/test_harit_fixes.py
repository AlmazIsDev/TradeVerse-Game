"""Регрессионные проверки исправлений ветки Harit."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from bank_p2p import _total_due
from clicker import build_case_pool, reward_asset_catalog
from notifications import build_notification_query, unread_categories


def test_component_case_pool_is_validated_before_spending():
    catalog = [{"category": "gpu"}, {"category": "cpu"}]
    assert build_case_pool("gpu", catalog) == [{"category": "gpu"}]
    assert build_case_pool("missing", catalog) == []


def test_all_asset_case_rewards_resolve_to_catalog_items():
    catalog = [
        {"slug": "citycar", "type": "car", "name": "Car"},
        {"slug": "studio", "type": "realestate", "name": "Home"},
        {"slug": "coffee", "type": "business", "name": "Business"},
    ]
    for reward_type, asset_type in (("car", "car"), ("house", "realestate"), ("business", "business")):
        assert reward_asset_catalog(reward_type, catalog)["type"] == asset_type


def test_notification_query_keeps_category_and_exclusion_filters():
    assert build_notification_query("u1", "market", None) == {"userId": "u1", "category": "market"}
    assert build_notification_query("u1", None, "automatic") == {"userId": "u1", "category": {"$ne": "automatic"}}


def test_unread_categories_counts_all_categories():
    notifications = [
        {"read": False, "category": "market"},
        {"read": False, "category": "market"},
        {"read": False, "category": "automatic"},
        {"read": True, "category": "market"},
    ]
    assert unread_categories(notifications) == {"market": 2, "automatic": 1}


def test_loan_due_amount_is_fixed_once_for_full_term():
    loan = {"amount": 1000, "owed": 140, "recovered": 0}
    assert _total_due(loan) == 1140
    assert _total_due({**loan, "recovered": 200}) == 940


def test_locales_keep_clicker_navigation_and_translations():
    import json
    from pathlib import Path

    for language in ("ru", "en", "es", "ja"):
        data = json.loads(Path(__file__).parents[1].joinpath("frontend/src/i18n/locales", f"{language}.json").read_text(encoding="utf-8"))
        assert data["nav"]["clicker"]
        assert data["clicker"]["title"]
        assert data["clicker"]["cases"]["basic"]
