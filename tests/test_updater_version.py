"""Tests de la versión leída desde VERSION.txt (single source of truth)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestVersionLabel(unittest.TestCase):
    def test_version_file_exists_and_non_empty(self):
        version_file = REPO_ROOT / "VERSION.txt"
        self.assertTrue(version_file.exists(), "Falta VERSION.txt en la raíz del repo")
        content = version_file.read_text(encoding="utf-8").strip()
        self.assertTrue(content, "VERSION.txt está vacío")
        # Convención: versión no vacía. Acepta tanto "V2_DD_MM_YYYY_n"
        # (formato histórico) como semver "1.0.0", "1.0.1", etc.
        # Validamos que el contenido no sea el sentinel de fallback.
        self.assertNotEqual(
            content,
            "V2_unknown",
            f"VERSION.txt contiene el sentinel 'V2_unknown' en vez de una version real",
        )

    def test_main_reads_same_version_as_file(self):
        # `main.py` lee APP_VERSION_LABEL dinámicamente desde VERSION.txt.
        # Si se importa varias veces, se cachea; forzamos relectura del fichero.
        from main import _read_version_label  # noqa: E402

        version_file = REPO_ROOT / "VERSION.txt"
        expected = version_file.read_text(encoding="utf-8").strip()
        self.assertEqual(_read_version_label(), expected)

    def test_updater_compare_with_version_file(self):
        # El tag remoto se compara por igualdad con APP_VERSION_LABEL; si
        # también viene de VERSION.txt, la igualdad debe dar "actualizado".
        from main import APP_VERSION_LABEL
        from src.core.updater import compare_versions  # noqa: E402

        self.assertFalse(compare_versions(APP_VERSION_LABEL, APP_VERSION_LABEL))


if __name__ == "__main__":
    unittest.main()