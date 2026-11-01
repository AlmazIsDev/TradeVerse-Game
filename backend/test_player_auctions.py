"""Тесты аукциона бизнесов: проверки выставления, ставок и закрытия."""
import pytest

from game_config import PLAYER_AUCTION_CONFIG as CFG
import player_auctions as pa


def test_fee_and_step_are_sane():
    assert 0 < CFG["fee_pct"] < 1
    assert CFG["bid_step"] > 1
    assert 0 < CFG["reprice"] < 1
    assert 0 < CFG["min_ratio"] <= 1


def test_listing_rejects_non_positive_price():
    with pytest.raises(ValueError):
        pa.ListingCreate(assetId="x", startPrice=0)


def test_listing_rejects_price_above_max():
    with pytest.raises(ValueError):
        pa.ListingCreate(assetId="x", startPrice=CFG["max_price"] + 1)


def test_listing_rounds_price_to_cents():
    listing = pa.ListingCreate(assetId="x", startPrice=100.555)
    assert listing.startPrice == 100.56


def test_oid_rejects_invalid_id():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        pa._oid("not-an-object-id")


def test_serialize_marks_seller_and_leader():
    from bson import ObjectId
    doc = {
        "_id": ObjectId(),
        "assetId": str(ObjectId()),
        "name": "Кафе",
        "slug": "cafe",
        "level": 2,
        "startPrice": 1000.0,
        "currentPrice": 1200.0,
        "topBidderId": "bidder",
        "topBidderName": "Иван",
        "sellerId": "seller",
        "sellerName": "Пётр",
        "endsAt": pa._now(),
        "status": "open",
    }
    as_seller = pa._serialize(doc, "seller")
    as_bidder = pa._serialize(doc, "bidder")
    assert as_seller["isSeller"] is True and as_seller["isMine"] is False
    assert as_bidder["isMine"] is True and as_bidder["isSeller"] is False
    assert as_seller["hasBids"] is True
    assert as_seller["minNextBid"] == round(1200.0 * CFG["bid_step"], 2)


def test_serialize_without_bids_min_bid_equals_current():
    from bson import ObjectId
    doc = {
        "_id": ObjectId(), "assetId": "a", "startPrice": 500.0, "currentPrice": 500.0,
        "topBidderId": None, "sellerId": "seller", "endsAt": pa._now(), "status": "open",
    }
    assert pa._serialize(doc, "other")["minNextBid"] == 500.0
