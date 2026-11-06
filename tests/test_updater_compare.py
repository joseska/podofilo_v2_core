"""Tests de comparación de versiones del updater."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.updater import compare_versions, _parse_version  # noqa: E402


class TestParseVersion(unittest.TestCase):
    def test_simple_semver(self):
        self.assertEqual(_parse_version("1.0.5"), (1, 0, 5))

    def test_v_prefix_is_tolerated(self):
        self.assertEqual(_parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(_parse_version("V1.2.3"), (1, 2, 3))

    def test_historical_format_not_supported(self):
        self.assertIsNone(_parse_version("V2_12_08_2026_2"))

    def test_prerelease_suffix_not_supported(self):
        self.assertIsNone(_parse_version("1.0.5-beta"))

    def test_empty_returns_none(self):
        self.assertIsNone(_parse_version(""))
        self.assertIsNone(_parse_version("   "))


class TestCompareVersions(unittest.TestCase):
    def test_same_version_means_no_update(self):
        self.assertFalse(compare_versions("1.0.5", "1.0.5"))

    def test_remote_greater_means_update(self):
        self.assertTrue(compare_versions("1.0.4", "1.0.5"))

    def test_remote_lower_is_not_an_update_downgrade_case(self):
        # Caso del bug: dev local 1.0.5 no publicada, GitHub latest=1.0.4.
        self.assertFalse(compare_versions("1.0.5", "1.0.4"))

    def test_numeric_order_not_lexicographic(self):
        self.assertTrue(compare_versions("1.0.9", "1.0.10"))

    def test_major_minor_and_patch_compares(self):
        self.assertTrue(compare_versions("1.0.5", "2.0.0"))
        self.assertTrue(compare_versions("1.2.5", "1.3.0"))
        self.assertFalse(compare_versions("2.0.0", "1.0.5"))

    def test_v_prefix_in_tag(self):
        self.assertTrue(compare_versions("1.0.5", "v1.0.6"))

    def test_fallback_unparseable_local_offers_update(self):
        # Local sin versión legible: se ofrece la release publicada.
        self.assertTrue(compare_versions("V2_unknown", "1.0.4"))

    def test_fallback_historical_tag_vs_semver(self):
        # Formato histórico cae al fallback (desigualdad) al no parsear.
        self.assertTrue(compare_versions("V2_12_08_2026_2", "1.0.4"))

    def test_fallback_equal_strings_means_no_update(self):
        self.assertFalse(compare_versions("V2_unknown", "V2_unknown"))

    def test_empty_local_disables_update(self):
        self.assertFalse(compare_versions("", "1.0.5"))

    def test_empty_remote_disables_update(self):
        self.assertFalse(compare_versions("1.0.5", ""))

    def test_both_empty_disables_update(self):
        self.assertFalse(compare_versions("", ""))

    def test_whitespace_is_stripped(self):
        # El trimming debe tolerar saltos de línea del VERSION.txt.
        self.assertFalse(compare_versions("  1.0.5  ", "1.0.5\n"))
        self.assertTrue(compare_versions("1.0.5", "  1.0.6  "))
        self.assertFalse(compare_versions("  1.0.5  ", "  1.0.5  "))


if __name__ == "__main__":
    unittest.main()