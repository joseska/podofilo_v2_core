"""Tests de regresión para la conversión XML -> PDF A4."""

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

from src.ingest.xml_to_pdf import convert_xml_file_to_pdf  # noqa: E402


class TestXmlToPdfConversion(unittest.TestCase):
    """Valida que el XML se convierta a PDF legible sin depender de la UI."""

    def setUp(self) -> None:
        # Cada test usa un directorio temporal aislado.
        self._tmpdir = TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        # Limpieza explícita del directorio temporal.
        self._tmpdir.cleanup()

    def test_convert_basic_xml_creates_pdf_with_expected_text(self) -> None:
        """Convierte un XML pequeño y comprueba que el texto aparece en el PDF."""
        xml_path = self.tmp_path / "justificante_inside.xml"
        xml_path.write_text(
            """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<token>
  <Identificador>ES_EA0020406_2026_EXP_202524240_2</Identificador>
  <UUID>fca8a534-076c-4e44-a4e2-3640c15f063e</UUID>
</token>
""",
            encoding="utf-8",
        )

        pdf_path = self.tmp_path / "justificante_inside.xml.pdf"
        result_path = convert_xml_file_to_pdf(xml_path, pdf_path)

        self.assertEqual(result_path, pdf_path)
        self.assertTrue(pdf_path.exists())

        with fitz.open(str(pdf_path)) as doc:
            self.assertGreaterEqual(len(doc), 1)
            text = "\n".join(page.get_text("text") for page in doc)

        self.assertIn("<token>", text)
        self.assertIn("Identificador", text)
        self.assertIn("fca8a534-076c-4e44-a4e2-3640c15f063e", text)

    def test_convert_long_xml_spans_multiple_pages(self) -> None:
        """Un XML largo debe repartirse en varias páginas A4."""
        xml_path = self.tmp_path / "largo.xml"

        # Generamos muchas líneas para forzar paginación.
        lines = ["<root>"]
        for i in range(900):
            lines.append(f"  <linea indice=\"{i}\">contenido {i}</linea>")
        lines.append("</root>")

        xml_path.write_text("\n".join(lines), encoding="utf-8")

        pdf_path = self.tmp_path / "largo.xml.pdf"
        convert_xml_file_to_pdf(xml_path, pdf_path)

        with fitz.open(str(pdf_path)) as doc:
            self.assertGreater(len(doc), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
