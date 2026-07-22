import unittest

from assets import (
    CATALOG, CATALOG_BY_SLUG, _income_per_hour, _rent_daily_rate,
    _sell_rate, _upgrade_cost, _upkeep_per_hour,
)
from businesses import _taxi_period, _vehicle_view


class AssetCatalogTests(unittest.TestCase):
    def test_required_catalog_is_complete_and_unique(self):
        required_businesses = {
            "taxi_fleet", "auto_service", "car_dealership", "logistics", "courier",
            "construction", "restaurant", "cafe", "bar", "hotel", "hostel", "fitness",
            "supermarket", "pharmacy", "gas_station", "carwash", "warehouse_complex",
            "data_center", "ad_agency", "print_shop", "radio_station", "tv_channel",
            "farm", "fishery", "sawmill", "factory", "jewelry", "shopping_mall",
            "business_center",
        }
        required_properties = {
            "apartment", "house", "cottage", "mansion", "garage", "parking_space",
            "warehouse", "hangar", "office", "commercial_unit", "land_plot",
            "industrial_site",
        }
        slugs = {item["slug"] for item in CATALOG}
        self.assertEqual(len(slugs), len(CATALOG))
        self.assertTrue(required_businesses.issubset(slugs))
        self.assertTrue(required_properties.issubset(slugs))

    def test_every_business_has_management_metadata(self):
        businesses = [item for item in CATALOG if item["type"] == "business"]
        self.assertGreaterEqual(len(businesses), 29)
        for item in businesses:
            self.assertGreater(item["price"], 0)
            self.assertGreater(item["employees"], 0)
            self.assertTrue(item["meta"]["mechanic"])
            self.assertTrue(item["meta"]["metric"])

    def test_staffing_and_salary_affect_profit(self):
        cafe = dict(CATALOG_BY_SLUG["cafe"])
        cafe["level"] = 1
        cafe["staff"] = []
        low_income = _income_per_hour(cafe)
        cafe["staff"] = [
            {"salary": 10, "role": "worker"} for _ in range(cafe["employees"])
        ]
        self.assertGreater(_income_per_hour(cafe), low_income)
        self.assertGreater(_upkeep_per_hour(cafe), cafe["upkeep_per_hour"] * 0.55)

    def test_price_drives_sale_rent_and_upgrade(self):
        asset = dict(CATALOG_BY_SLUG["mansion"])
        asset.update({"level": 1, "sell_rate": 0.6})
        before = (
            asset["price"] * _sell_rate(asset),
            _rent_daily_rate(asset),
            _upgrade_cost(asset),
        )
        asset["price"] *= 2
        after = (
            asset["price"] * _sell_rate(asset),
            _rent_daily_rate(asset),
            _upgrade_cost(asset),
        )
        self.assertEqual(after[0], before[0] * 2)
        self.assertEqual(after[1], before[1] * 2)
        self.assertEqual(after[2], before[2] * 2)

    def test_taxi_vehicle_stats_are_exposed(self):
        car = dict(CATALOG_BY_SLUG["sedan"])
        car.update({
            "_id": "vehicle-1", "condition": 83, "fuel": 41,
            "driverId": "driver-1", "level": 1,
        })
        row = _vehicle_view(car, [{"id": "driver-1", "name": "Alex"}])
        self.assertEqual(row["driver"]["name"], "Alex")
        self.assertGreater(row["incomePerHour"], 0)
        self.assertGreater(row["fuelPerHour"], 0)
        self.assertEqual(row["condition"], 83)

    def test_taxi_requires_driver_and_available_fuel(self):
        car = dict(CATALOG_BY_SLUG["citycar"])
        car.update({"condition": 100, "fuel": 10})
        self.assertEqual(_taxi_period(car, None, 4)["net"], 0)
        period = _taxi_period(car, {"salary": 10}, 24)
        self.assertLessEqual(period["fuelUsed"], 10)
        self.assertLess(period["hours"], 24)
        self.assertGreater(period["net"], 0)

    def test_gas_station_discount_reduces_fuel_cost(self):
        car = dict(CATALOG_BY_SLUG["sedan"])
        car.update({"condition": 100, "fuel": 100})
        driver = {"salary": 15}
        regular = _taxi_period(car, driver, 2, 0)
        discounted = _taxi_period(car, driver, 2, 0.12)
        self.assertLess(discounted["fuelCost"], regular["fuelCost"])
        self.assertGreater(discounted["net"], regular["net"])


if __name__ == "__main__":
    unittest.main()
