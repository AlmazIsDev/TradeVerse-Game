import pytest

from cityroof import _league_for_net_worth, ROOM_CAPACITY, ensure_player_room


def test_league_for_net_worth_boundaries():
    assert _league_for_net_worth(0) == "novice"
    assert _league_for_net_worth(1_000_000) == "bronze"
    assert _league_for_net_worth(25_000_000) == "silver"
    assert _league_for_net_worth(250_000_000) == "gold"
    assert _league_for_net_worth(1_000_000_000) == "platinum"
    assert _league_for_net_worth(5_000_000_000) == "diamond"


@pytest.mark.asyncio
async def test_room_capacity_creates_next_room():
    class FakeRooms:
        def __init__(self):
            self.rooms = []

        async def find_one(self, query, *args, **kwargs):
            return next((room for room in self.rooms if room["season"] == 1 and room["league"] == "novice" and len(room["member_ids"]) < ROOM_CAPACITY), None)

        async def count_documents(self, query):
            return len(self.rooms)

        async def insert_one(self, room):
            room["_id"] = len(self.rooms) + 1
            self.rooms.append(room)

    class FakeDb:
        cityroof_rooms = FakeRooms()

    room = await ensure_player_room(FakeDb(), "user-1", 1, 0)
    assert room["league"] == "novice"
    assert room["member_ids"] == ["user-1"]
    assert ROOM_CAPACITY == 8


def test_interval_amount_uses_league_multiplier():
    from cityroof import _interval_amount

    assert _interval_amount(100_000, "diamond") > _interval_amount(100_000, "gold")
    assert _interval_amount(100_000, "novice") == round(100_000 / 288, 2)


def test_leagues_have_distinct_market_parameters():
    from cityroof import DEFAULT_WARCOIN_CONFIG

    leagues = DEFAULT_WARCOIN_CONFIG["leagues"]
    assert len({item["warcoinPrice"] for item in leagues}) == 6
    assert len({item["attackCost"] for item in leagues}) == 6


def test_league_multiplier_preserves_dollar_value():
    from cityroof import LEAGUE_MULTIPLIERS, LEAGUE_WARCOIN_PRICES, _migrate_warcoin_amount

    assert LEAGUE_MULTIPLIERS["bronze"] == 25
    assert LEAGUE_MULTIPLIERS["diamond"] == 20_000
    assert LEAGUE_WARCOIN_PRICES["diamond"] == 1_000_000
    assert _migrate_warcoin_amount(20_000, "diamond") == 1


def test_business_bonus_view_scales_daily_income():
    from cityroof import _business_bonus_view

    view = _business_bonus_view("market", "diamond")
    assert view["daily"] == 55_000 * 20_000
    assert view["leagueMultiplier"] == 20_000
