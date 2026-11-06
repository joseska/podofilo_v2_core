"""Tests mínimos de regresión para el pipeline de ingestión.

Objetivo:
- Validar la normalización y filtrado de rutas locales en `IngestPipeline.normalize_local_paths`.
- Evitar regresiones al unificar todas las entradas (drag&drop, diálogo, watcher, OVE post-descarga).

Nota:
- Estos tests NO requieren PDFs reales: basta con ficheros que existan y terminen en `.pdf`.
- Usamos `unittest` para no añadir dependencias extra.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


# Aseguramos que la raíz del repo esté en sys.path para poder importar `src.*`
# cuando ejecutamos `python -m unittest ...` desde el root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ingest.pipeline import IngestPipeline, IngestSource  # noqa: E402


class TestIngestPipelineNormalizeLocalPaths(unittest.TestCase):
    """Cubre los casos más importantes del pipeline sin depender de la UI."""

    def setUp(self) -> None:
        # Creamos un directorio temporal aislado por test.
        self._tmpdir = TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

        # Instanciamos el pipeline (clase pequeña, sin dependencias externas).
        self.pipeline = IngestPipeline()

    def tearDown(self) -> None:
        # Liberamos el directorio temporal.
        self._tmpdir.cleanup()

    def _touch(self, filename: str) -> Path:
        """Crea un fichero vacío en el tmpdir y devuelve su ruta."""
        p = self.tmp_path / filename
        p.write_bytes(b"")
        return p

    def test_accepts_str_and_path(self) -> None:
        """Acepta rutas como `str` y como `Path` y devuelve siempre `Path`."""
        a = self._touch("a.pdf")
        b = self._touch("b.pdf")

        res = self.pipeline.normalize_local_paths(
            source=IngestSource.DRAG_DROP,
            paths=[str(a), b],
        )

        self.assertEqual(len(res.normalized_paths), 2)
        self.assertTrue(all(isinstance(p, Path) for p in res.normalized_paths))

    def test_filters_not_found(self) -> None:
        """Una ruta .pdf que no existe se descarta con reason='not_found'."""
        missing = self.tmp_path / "missing.pdf"

        res = self.pipeline.normalize_local_paths(
            source=IngestSource.FILE_DIALOG,
            paths=[missing],
        )

        self.assertEqual(res.normalized_paths, [])
        self.assertEqual(len(res.skipped), 1)
        self.assertEqual(res.skipped[0].reason, "not_found")

    def test_filters_not_pdf_and_accepts_uppercase_pdf(self) -> None:
        """Filtra extensiones no PDF y acepta .PDF en mayúsculas."""
        txt = self._touch("c.txt")
        pdf_upper = self._touch("D.PDF")

        res = self.pipeline.normalize_local_paths(
            source=IngestSource.STARTUP,
            paths=[txt, pdf_upper],
        )

        self.assertEqual(len(res.normalized_paths), 1)
        self.assertEqual(res.normalized_paths[0].name, "D.PDF")
        self.assertEqual(len(res.skipped), 1)
        self.assertEqual(res.skipped[0].reason, "not_pdf")

    def test_dedupe_preserves_order(self) -> None:
        """Elimina duplicados preservando el orden de entrada."""
        a = self._touch("a.pdf")
        b = self._touch("b.pdf")

        res = self.pipeline.normalize_local_paths(
            source=IngestSource.WATCHER,
            paths=[a, a, b],
        )

        self.assertEqual([p.name for p in res.normalized_paths], ["a.pdf", "b.pdf"])
        self.assertTrue(any(s.reason == "duplicate" for s in res.skipped))

    def test_relative_path_becomes_absolute(self) -> None:
        """Una ruta relativa se normaliza (best-effort) a absoluta."""
        self._touch("rel.pdf")

        old_cwd = os.getcwd()
        try:
            os.chdir(self.tmp_path)
            res = self.pipeline.normalize_local_paths(
                source=IngestSource.UNKNOWN,
                paths=["rel.pdf"],
            )
        finally:
            os.chdir(old_cwd)

        self.assertEqual(len(res.normalized_paths), 1)
        self.assertEqual(res.normalized_paths[0].name, "rel.pdf")
        self.assertTrue(res.normalized_paths[0].is_absolute())

    def test_none_and_empty_paths_do_not_crash(self) -> None:
        """`paths=None` o vacío no debe lanzar excepciones."""
        res_none = self.pipeline.normalize_local_paths(
            source=IngestSource.UNKNOWN,
            paths=None,
        )
        self.assertEqual(res_none.normalized_paths, [])

        res_empty = self.pipeline.normalize_local_paths(
            source=IngestSource.UNKNOWN,
            paths=[],
        )
        self.assertEqual(res_empty.normalized_paths, [])

    def test_invalid_path_values_are_skipped(self) -> None:
        """Valores no convertibles a Path se descartan con reason='path_invalid'."""
        res = self.pipeline.normalize_local_paths(
            source=IngestSource.UNKNOWN,
            paths=[None, object()],
        )

        self.assertEqual(res.normalized_paths, [])
        self.assertEqual(len(res.skipped), 2)
        self.assertTrue(all(s.reason == "path_invalid" for s in res.skipped))


if __name__ == "__main__":
    unittest.main(verbosity=2)
