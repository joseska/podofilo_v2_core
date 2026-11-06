"""
Generador de página de índice PDF.

Crea un PDF temporal con una o varias páginas que listan los nombres de los
documentos/secciones que componen el expediente actual.
"""

import logging
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import fitz  # PyMuPDF

log = logging.getLogger(__name__)

# ---- Constantes de maquetación (puntos PDF: 1 pt ≈ 1/72 pulgada) ----
PAGE_WIDTH = 595.28      # A4
PAGE_HEIGHT = 841.89     # A4
MARGIN_LEFT = 60
MARGIN_TOP = 70
MARGIN_RIGHT = 60
MARGIN_BOTTOM = 60

TITLE_FONT_SIZE = 22
ITEM_FONT_SIZE = 13
LINE_SPACING = 1.45       # multiplicador sobre ITEM_FONT_SIZE

TITLE_COLOR = (0.18, 0.18, 0.18)
ITEM_COLOR = (0.15, 0.15, 0.15)
BULLET_COLOR = (0.35, 0.35, 0.35)
ACCENT_COLOR = (0.16, 0.47, 0.82)   # línea decorativa bajo título


def generate_index_pdf(
    entry_names: List[str],
    title: str = "INDICE",
    temp_dir: Optional[str] = None,
    page_ranges: Optional[List[Tuple[int, int]]] = None,
    filename_suffix: str = "",
) -> Path:
    """
    Genera un archivo PDF con el índice de *entry_names* y devuelve la ruta.

    Parameters
    ----------
    entry_names : list[str]
        Nombres a listar (sin extensión). Si está vacío, genera una página
        con un mensaje informativo.
    title : str
        Título que aparece en la parte superior de la página.
    temp_dir : str | None
        Directorio temporal donde guardar el PDF. Si es ``None`` se usa
        ``tempfile.gettempdir()``.
    page_ranges : list[tuple[int, int]] | None
        Lista opcional de tuplas (primera_pagina, ultima_pagina) para cada
        entrada. Si se proporciona, se muestra "nombre (Páginas X - Y)".
    filename_suffix : str
        Sufijo opcional para el nombre de archivo temporal. Se usa para
        evitar colisiones de caché al regenerar el índice.

    Returns
    -------
    Path
        Ruta absoluta al PDF generado.
    """
    if temp_dir is None:
        temp_dir = tempfile.gettempdir()

    suffix = f"_{filename_suffix}" if filename_suffix else ""
    output_path = Path(temp_dir) / f"_podofilo_index_tmp{suffix}.pdf"

    doc = fitz.open()
    usable_height = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    # ---- Preparar lineas del indice ----
    if not entry_names:
        lines = ["(Sin documentos)"]
    elif page_ranges and len(page_ranges) == len(entry_names):
        lines = []
        for name, (pg_start, pg_end) in zip(entry_names, page_ranges):
            if pg_start == pg_end:
                lines.append(f"{name}  (Pag. {pg_start})")
            else:
                lines.append(f"{name}  (Pags. {pg_start} - {pg_end})")
    else:
        lines = list(entry_names)

    # ---- Funciones de word-wrap ----
    text_start_x = MARGIN_LEFT + 14  # Posicion X donde empieza el texto (tras bullet)
    max_text_width = PAGE_WIDTH - text_start_x - MARGIN_RIGHT  # Ancho util

    def _wrap_line(text: str) -> List[str]:
        """Divide *text* en sub-lineas que caben en *max_text_width*."""
        words = text.split()
        if not words:
            return [""]

        wrapped: List[str] = []
        current = words[0]

        for word in words[1:]:
            test = current + " " + word
            tw = fitz.get_text_length(test, fontname="helv", fontsize=ITEM_FONT_SIZE)
            if tw > max_text_width:
                wrapped.append(current)
                current = word
            else:
                current = test

        wrapped.append(current)
        return wrapped

    # Pre-envolver todas las lineas para calcular layout completo
    wrapped_items: List[Tuple[str, List[str]]] = []  # (original, sub_lineas)
    for name in lines:
        sub_lines = _wrap_line(name)
        wrapped_items.append((name, sub_lines))

    # ---- Generar paginas con word-wrap ----
    item_line_height = ITEM_FONT_SIZE * LINE_SPACING
    title_block_height = TITLE_FONT_SIZE + 14

    item_idx = 0
    page_num = 0

    while item_idx < len(wrapped_items):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

        if page_num == 0:
            # --- Titulo (solo primera pagina) ---
            line_y = MARGIN_TOP + TITLE_FONT_SIZE + 6
            page.draw_line(
                fitz.Point(MARGIN_LEFT, line_y),
                fitz.Point(PAGE_WIDTH - MARGIN_RIGHT, line_y),
                color=ACCENT_COLOR,
                width=2.0,
            )
            page.insert_text(
                fitz.Point(MARGIN_LEFT, MARGIN_TOP + TITLE_FONT_SIZE),
                title,
                fontsize=TITLE_FONT_SIZE,
                fontname="helv",
                color=TITLE_COLOR,
            )

            content_top = MARGIN_TOP + title_block_height + 14
            available_height = usable_height - title_block_height - 24
        else:
            content_top = MARGIN_TOP + 10
            available_height = usable_height - 20

        # Cuantas sub-lineas caben en esta pagina
        sub_lines_available = max(1, int(available_height / item_line_height))

        y = content_top
        lines_drawn = 0

        while item_idx < len(wrapped_items) and lines_drawn < sub_lines_available:
            _orig_name, sub_lines = wrapped_items[item_idx]
            needed = len(sub_lines)
            remaining = sub_lines_available - lines_drawn

            # Si este item no cabe completo, ver si podemos meter al menos una sub-linea
            if needed > remaining:
                if lines_drawn == 0:
                    needed = remaining  # Pagina vacia: meter lo que quepa
                else:
                    break  # No cabe, pasara a la siguiente pagina

            # Dibujar sub-lineas de este item
            for sub_idx in range(needed):
                sub_text = sub_lines[sub_idx]
                if sub_idx == 0:
                    bullet_y = y + ITEM_FONT_SIZE - 1
                    page.draw_circle(
                        fitz.Point(MARGIN_LEFT + 3, bullet_y - 3),
                        2.5,
                        color=BULLET_COLOR,
                        fill=BULLET_COLOR,
                    )
                    page.insert_text(
                        fitz.Point(text_start_x, y + ITEM_FONT_SIZE),
                        sub_text,
                        fontsize=ITEM_FONT_SIZE,
                        fontname="helv",
                        color=ITEM_COLOR,
                    )
                else:
                    # Sub-lineas adicionales: sangria extra
                    page.insert_text(
                        fitz.Point(text_start_x + 6, y + ITEM_FONT_SIZE),
                        sub_text,
                        fontsize=ITEM_FONT_SIZE,
                        fontname="helv",
                        color=ITEM_COLOR,
                    )
                y += item_line_height
                lines_drawn += 1

            item_idx += 1

        page_num += 1

    # ---- Guardar ----
    doc.save(str(output_path), garbage=4, deflate=True)
    doc.close()

    log.info(f"PDF de indice generado: {output_path} ({page_num} pags, {len(lines)} entradas)")
    return output_path
