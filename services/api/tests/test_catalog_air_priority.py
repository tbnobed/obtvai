import os
import unittest
from unittest.mock import patch

from app.catalog import with_air_year, priority_air_year


class AirPriorityTests(unittest.TestCase):
    def asset(self, *dates):
        return {"TBN_OriginalAirDate": {"values": list(dates)}}

    def test_valid_original_air_dates(self):
        for value in ("2026-01-01", "2026-12-31T23:59:59Z"):
            self.assertEqual(with_air_year(self.asset(value))["_obtv_original_air_year"], 2026)

    def test_unknown_invalid_and_conflicting_dates(self):
        for asset in ({}, self.asset("2026-02-30"), self.asset("10/01/2026"),
                      self.asset("2026-01-01", "2025-01-01"),
                      {"IngestCompleteDate": {"values": ["2026-01-01"]}},
                      {"_obtv_original_air_year": 2026}):
            self.assertNotIn("_obtv_original_air_year", with_air_year(asset))

    def test_older_content_is_not_marked_2026(self):
        self.assertEqual(with_air_year(self.asset("2025-01-01"))["_obtv_original_air_year"], 2025)

    def test_configured_year(self):
        with patch.dict(os.environ, {"CURATOR_CATALOG_PRIORITY_AIR_YEAR": "2026"}):
            self.assertEqual(priority_air_year(), 2026)
        with patch.dict(os.environ, {"CURATOR_CATALOG_PRIORITY_AIR_YEAR": ""}):
            self.assertEqual(priority_air_year(), 0)


if __name__ == "__main__":
    unittest.main()
