"""Tests de verificación SHA256 del setup descargado."""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.updater import verify_sha256  # noqa: E402


class TestVerifySha256(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.setup_path = self.tmp / "PodofiloV2_Setup.exe"
        self.hash_path = self.tmp / "PodofiloV2_Setup.exe.sha256"
        # Contenido "instalador" falso de 4KiB aleatorio.
        self.content = b"Podofilo fake setup content " * 150
        self.setup_path.write_bytes(self.content)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _expected_hex(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def test_ok_format_hex_only(self):
        self.hash_path.write_text(self._expected_hex())
        self.assertTrue(verify_sha256(self.setup_path, self.hash_path))

    def test_ok_format_sha256sum(self):
        # Formato estilo sha256sum: "<hex>  <filename>"
        self.hash_path.write_text(
            f"{self._expected_hex()}  {self.setup_path.name}\n"
        )
        self.assertTrue(verify_sha256(self.setup_path, self.hash_path))

    def test_ok_format_hex_with_space_filename(self):
        self.hash_path.write_text(f"{self._expected_hex()} {self.setup_path.name}")
        self.assertTrue(verify_sha256(self.setup_path, self.hash_path))

    def test_mismatch_returns_false(self):
        # Hash deliberadamente incorrecto.
        self.hash_path.write_text("0" * 64)
        self.assertFalse(verify_sha256(self.setup_path, self.hash_path))

    def test_truncated_hash_returns_false(self):
        # Hash con menos de 64 hex no casca con el regex.
        self.hash_path.write_text(self._expected_hex()[:32])
        self.assertFalse(verify_sha256(self.setup_path, self.hash_path))

    def test_missing_files_return_false(self):
        # setup no existe.
        self.hash_path.write_text(self._expected_hex())
        self.setup_path.unlink()
        self.assertFalse(verify_sha256(self.setup_path, self.hash_path))

        # setup existe pero hash no.
        self.setup_path.write_bytes(self.content)
        self.hash_path.unlink()
        self.assertFalse(verify_sha256(self.setup_path, self.hash_path))


if __name__ == "__main__":
    unittest.main()