"""Tests de regresión para carga defensiva de PageReference en PdfViewer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz


# Aseguramos que la raíz del repo esté en sys.path para poder importar `src.*`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.pdf.structure import PageReference  # noqa: E402
from src.ui.pdf_viewer import PdfViewer  # noqa: E402


class TestPdfViewerPageRefs(unittest.TestCase):
    """Valida que referencias obsoletas no rompan la expansión del visor."""

    def setUp(self) -> None:
        # Cada test usa un directorio temporal aislado para no tocar ficheros reales.
        self._tmpdir = TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        # Limpieza explícita de recursos temporales al final del test.
        self._tmpdir.cleanup()

    def _create_pdf(self, filename: str, pages: int) -> Path:
        """Crea un PDF de prueba con el número de páginas indicado."""
        pdf_path = self.tmp_path / filename
        doc = fitz.open()
        try:
            # Añadimos páginas simples para construir un PDF válido mínimo.
            for _ in range(pages):
                doc.new_page(width=595, height=842)
            doc.save(str(pdf_path))
        finally:
            doc.close()
        return pdf_path

    def test_load_from_page_refs_skips_out_of_range_refs(self) -> None:
        """Si una referencia apunta fuera de rango, se ignora y no rompe el flujo."""
        pdf_path = self._create_pdf("one_page.pdf", pages=1)
        viewer = PdfViewer()

        refs = [
            PageReference(file_path=str(pdf_path), page_index=0),  # válido
            PageReference(file_path=str(pdf_path), page_index=1),  # inválido (solo existe página 0)
        ]

        loaded_count = viewer.load_from_page_refs(refs)

        # Debe cargar solo la referencia válida.
        self.assertEqual(loaded_count, 1)
        self.assertEqual(viewer.get_page_count(), 1)

        # Además, calcular tamaños no debe lanzar IndexError aunque hubiese refs inválidas de entrada.
        sizes = viewer.get_all_page_sizes()
        self.assertEqual(len(sizes), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
