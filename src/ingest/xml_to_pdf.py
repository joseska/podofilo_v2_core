"""Utilidades de conversión XML -> PDF (A4).

Este módulo permite convertir un XML a un PDF legible tipo "documento impreso".
El objetivo es reutilizar el flujo actual de PDFs sin forzar al resto de la aplicación
(visor, cajas, guardado, numeración, etc.) a entender XML nativamente.
"""

from __future__ import annotations

from pathlib import Path
import textwrap

import fitz


# Tamaño A4 en puntos PDF (72 dpi lógicos): 595 x 842.
A4_WIDTH_PT = 595.0
A4_HEIGHT_PT = 842.0

# Ajustes por defecto para un texto monoespaciado legible.
DEFAULT_MARGIN_PT = 40.0
DEFAULT_FONT_SIZE_PT = 10.0
DEFAULT_FONT_NAME = "courier"
DEFAULT_LINE_HEIGHT_FACTOR = 1.35

# Codificaciones comunes para XML en entornos Windows/administración.
XML_ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _read_xml_text_with_fallback(xml_path: Path) -> str:
    """Lee el XML como texto con fallback de codificación.

    Primero intentamos codificaciones habituales; si todas fallan,
    decodificamos con reemplazo para no bloquear la conversión.
    """
    raw_bytes = xml_path.read_bytes()

    for encoding in XML_ENCODING_CANDIDATES:
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw_bytes.decode("utf-8", errors="replace")

    # Normalizamos saltos de línea para que el layout sea estable.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _wrap_text_lines(text: str, max_chars_per_line: int) -> list[str]:
    """Divide el texto en líneas ajustadas al ancho máximo estimado.

    Usamos `textwrap` para evitar que líneas largas desborden el ancho de página.
    """
    wrapped_lines: list[str] = []

    for raw_line in text.split("\n"):
        # Expandimos tabs para que el ancho visual sea más predecible.
        expanded = raw_line.expandtabs(4)

        if not expanded:
            wrapped_lines.append("")
            continue

        chunks = textwrap.wrap(
            expanded,
            width=max_chars_per_line,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        )

        if chunks:
            wrapped_lines.extend(chunks)
        else:
            wrapped_lines.append("")

    return wrapped_lines or [""]


def convert_xml_file_to_pdf(
    xml_path: Path,
    output_pdf_path: Path,
    *,
    margin_pt: float = DEFAULT_MARGIN_PT,
    font_size_pt: float = DEFAULT_FONT_SIZE_PT,
    font_name: str = DEFAULT_FONT_NAME,
) -> Path:
    """Convierte un fichero XML local a un PDF A4 de solo texto.

    La conversión es deliberadamente simple: se imprime el contenido textual del XML
    en páginas A4 con fuente monoespaciada.
    """
    xml_path = Path(xml_path)
    output_pdf_path = Path(output_pdf_path)

    if not xml_path.exists() or not xml_path.is_file():
        raise FileNotFoundError(f"XML no encontrado: {xml_path}")

    xml_text = _read_xml_text_with_fallback(xml_path)

    usable_width_pt = max(1.0, A4_WIDTH_PT - (2.0 * margin_pt))

    # Aproximación de ancho por carácter para fuente monoespaciada.
    approx_char_width_pt = max(1.0, font_size_pt * 0.60)
    max_chars_per_line = max(20, int(usable_width_pt / approx_char_width_pt))

    lines = _wrap_text_lines(xml_text, max_chars_per_line)

    line_height_pt = max(font_size_pt + 1.0, font_size_pt * DEFAULT_LINE_HEIGHT_FACTOR)
    usable_height_pt = max(1.0, A4_HEIGHT_PT - (2.0 * margin_pt))
    lines_per_page = max(1, int(usable_height_pt / line_height_pt))

    doc = fitz.open()
    try:
        # Repartimos líneas en bloques por página para controlar desbordes verticales.
        for start in range(0, len(lines), lines_per_page):
            page_lines = lines[start : start + lines_per_page]
            page = doc.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)

            y = margin_pt + font_size_pt
            for line in page_lines:
                page.insert_text(
                    (margin_pt, y),
                    line,
                    fontsize=font_size_pt,
                    fontname=font_name,
                    color=(0, 0, 0),
                )
                y += line_height_pt

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # Deflate + garbage reduce tamaño en temporales y exportaciones posteriores.
        doc.save(str(output_pdf_path), garbage=4, deflate=True)
    finally:
        doc.close()

    return output_pdf_path
