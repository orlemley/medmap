from __future__ import annotations

import unittest

from optimal_hospital_placer.api.query import diversify_ranked_rows, haversine_miles


def row(site: str, tract: str, latitude: float, longitude: float) -> dict:
    return {
        "site_id": site,
        "source_tract_geoid": tract,
        "latitude": latitude,
        "longitude": longitude,
        "query_score": 1.0,
    }


class DiversificationTests(unittest.TestCase):
    def test_keeps_only_best_ranked_point_per_tract(self):
        rows = [
            row("best", "tract-a", 40.0, -100.0),
            row("duplicate", "tract-a", 41.0, -101.0),
            row("other", "tract-b", 42.0, -102.0),
        ]
        selected, _ = diversify_ranked_rows(rows, 3, state="NE")
        self.assertEqual([item["site_id"] for item in selected], ["best", "other"])

    def test_spreads_top_results_before_relaxing_distance(self):
        rows = [
            row("one", "tract-1", 40.0, -100.0),
            row("near-one", "tract-2", 40.01, -100.01),
            row("two", "tract-3", 41.0, -101.0),
        ]
        selected, initial = diversify_ranked_rows(rows, 2, state=None)
        self.assertEqual([item["site_id"] for item in selected], ["one", "two"])
        self.assertGreaterEqual(haversine_miles(
            selected[0]["latitude"], selected[0]["longitude"],
            selected[1]["latitude"], selected[1]["longitude"],
        ), initial)

    def test_relaxes_distance_to_fill_requested_count(self):
        rows = [row(f"site-{i}", f"tract-{i}", 40.0, -100.0 + i * .01) for i in range(5)]
        selected, _ = diversify_ranked_rows(rows, 5, state=None)
        self.assertEqual(len(selected), 5)


if __name__ == "__main__":
    unittest.main()
