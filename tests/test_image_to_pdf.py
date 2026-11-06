"""Tests de regresión para conversión imagen -> PDF A4."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz
from PIL import Image


# Aseguramos que la raíz del repo esté en sys.path para poder importar `src.*`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ingest.image_to_pdf import convert_image_file_to_pdf  # noqa: E402


class TestImageToPdfConversion(unittest.TestCase):
    """Valida que PNG/JPG se conviertan a PDF sin depender de la UI."""

    def setUp(self) -> None:
        # Cada test usa un directorio temporal aislado.
        self._tmpdir = TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        # Limpieza explícita del directorio temporal.
        self._tmpdir.cleanup()

    def _create_image(self, filename: str, size: tuple[int, int], color: tuple[int, int, int]) -> Path:
        """Genera una imagen de prueba RGB para el test."""
        path = self.tmp_path / filename
        img = Image.new("RGB", size=size, color=color)
        img.save(path)
        return path

    def test_convert_png_creates_single_page_pdf(self) -> None:
        """Un PNG válido debe convertirse en PDF de una página."""
        image_path = self._create_image("prueba.png", size=(800, 1200), color=(10, 120, 220))
        pdf_path = self.tmp_path / "prueba.png.pdf"

        result_path = convert_image_file_to_pdf(image_path, pdf_path)

        self.assertEqual(result_path, pdf_path)
        self.assertTrue(pdf_path.exists())

        with fitz.open(str(pdf_path)) as doc:
            self.assertEqual(len(doc), 1)
            # Verificación mínima de que la página existe y tiene tamaño útil.
            self.assertGreater(doc[0].rect.width, 0)
            self.assertGreater(doc[0].rect.height, 0)

    def test_convert_landscape_jpg_uses_landscape_page(self) -> None:
        """Una imagen apaisada debe generar página PDF apaisada para mejor ajuste visual."""
        image_path = self._create_image("panorama.jpg", size=(1800, 900), color=(200, 80, 40))
        pdf_path = self.tmp_path / "panorama.jpg.pdf"

        convert_image_file_to_pdf(image_path, pdf_path)

        with fitz.open(str(pdf_path)) as doc:
            self.assertEqual(len(doc), 1)
            page_rect = doc[0].rect
            self.assertGreater(page_rect.width, page_rect.height)


if __name__ == "__main__":
    unittest.main(verbosity=2)
