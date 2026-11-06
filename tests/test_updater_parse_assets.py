"""Tests de parseo de assets de la release GitHub."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.updater import parse_assets, SETUP_ASSET_NAME, HASH_ASSET_NAME  # noqa: E402


def _asset(name: str, size: int = 1000, url: str = "") -> dict:
    return {
        "name": name,
        "size": size,
        "browser_download_url": url or f"https://example.com/{name}",
    }


class TestParseAssets(unittest.TestCase):
    def test_returns_setup_and_hash_when_both_present(self):
        release = {
            "tag_name": "V2_13_08_2026_1",
            "assets": [
                _asset(SETUP_ASSET_NAME, size=5_000_000),
                _asset(HASH_ASSET_NAME, size=99),
                _asset("otro.txt", size=10),
            ],
        }
        result = parse_assets(release)
        self.assertIsNotNone(result)
        setup, hash_ = result
        self.assertEqual(setup["name"], SETUP_ASSET_NAME)
        self.assertEqual(setup["size"], 5_000_000)
        self.assertEqual(hash_["name"], HASH_ASSET_NAME)

    def test_returns_none_when_setup_missing(self):
        release = {
            "tag_name": "V2",
            "assets": [_asset(HASH_ASSET_NAME)],
        }
        self.assertIsNone(parse_assets(release))

    def test_returns_none_when_hash_missing(self):
        release = {
            "tag_name": "V2",
            "assets": [_asset(SETUP_ASSET_NAME)],
        }
        self.assertIsNone(parse_assets(release))

    def test_returns_none_for_empty_release(self):
        self.assertIsNone(parse_assets({}))
        self.assertIsNone(parse_assets(None))

    def test_returns_none_when_no_assets(self):
        self.assertIsNone(parse_assets({"tag_name": "V2", "assets": []}))


if __name__ == "__main__":
    unittest.main()