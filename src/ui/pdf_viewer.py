"""
PDF Viewer - Manages PDF document display and page operations
"""
import logging
from pathlib import Path
from typing import List, Set
from PIL import Image

from src.pdf.document import PdfDocument
from src.pdf.cache import get_cache
from src.pdf.structure import PageReference

log = logging.getLogger(__name__)

class PdfViewer:
    """Manages PDF documents and page operations"""
    
    def __init__(self):
        """Initialize PDF viewer"""
        self.documents: List[PdfDocument] = []
        self.pages: List[tuple] = []  # [(doc_idx, page_num), ...]
        self.selected_pages: Set[int] = set()  # Set of page indices
        self.marked_pages: Set[int] = set()  # Set of marked (blank) page indices
        self.cache = get_cache()
        self.current_zoom = 100  # Percentage
        self.section_manager = None  # Will be set by main_window
        
    def load_pdf(self, filepath: str) -> int:
        """
        Load PDF file
        
        Args:
            filepath: Path to PDF file
            
        Returns:
            Number of pages loaded
        """
        try:
            doc = PdfDocument(filepath)
            doc_idx = len(self.documents)
            self.documents.append(doc)
            
            # Add all pages from this document
            for page_num in range(doc.page_count):
                self.pages.append((doc_idx, page_num))
            
            log.info(f"Loaded {doc.page_count} pages from {Path(filepath).name}")
            return doc.page_count
            
        except Exception as e:
            log.error(f"Failed to load PDF: {e}", exc_info=True)
            raise
    
    def get_page_count(self) -> int:
        """Get total number of pages across all documents"""
        return len(self.pages)
    
    def get_all_page_sizes(self) -> List[tuple]:
        """
        Get dimensions (width, height) for all pages
        Used for initializing grid layout with correct aspect ratios
        """
        sizes = []
        for item in self.pages:
            if not (isinstance(item, tuple) and len(item) == 2):
                log.warning(f"PdfViewer.pages contiene un elemento inválido ({type(item)}); ignorando")
                continue
            doc_idx, page_num = item
            doc = self.documents[doc_idx]
            sizes.append(doc.get_page_size(page_num))
        return sizes
    
    def get_page_thumbnail(self, page_idx: int, dpi: int = 72) -> Image.Image:
        """
        Get thumbnail for page
        
        Args:
            page_idx: Global page index
            dpi: Resolution for rendering
            
        Returns:
            PIL Image
        """
        if page_idx < 0 or page_idx >= len(self.pages):
            raise IndexError(f"Page index {page_idx} out of range")
        
        doc_idx, page_num = self.pages[page_idx]
        doc = self.documents[doc_idx]
        
        # Check cache first
        cache_key = f"{doc.filepath}:{page_num}:{dpi}"
        cached = self.cache.get(str(doc.filepath), page_num, dpi)
        if cached:
            return cached
        
        # Render and cache
        image = doc.render_page_thumbnail(page_num, dpi=dpi)
        self.cache.put(str(doc.filepath), page_num, dpi, image)
        
        return image
    
    def clear_cache(self):
        """Clear thumbnail cache for all documents"""
        for doc in self.documents:
            self.cache.clear_pdf(str(doc.filepath))
        log.info("Cleared thumbnail cache for all documents")
    
    def get_page_thumbnail_fast(self, page_idx: int, target_dpi: int) -> Image.Image:
        """
        Get thumbnail with fast rescaling for instant feedback
        
        Uses cached image at different DPI and rescales with BILINEAR for speed.
        Falls back to full render if no cached version exists.
        
        IMPORTANT: Only rescales when cached DPI is close to target (within 1.5x).
        If we need significantly higher resolution, we render fresh to avoid blurriness.
        
        Args:
            page_idx: Global page index
            target_dpi: Desired DPI
            
        Returns:
            PIL Image (may be lower quality, rescaled)
        """
        if page_idx < 0 or page_idx >= len(self.pages):
            raise IndexError(f"Page index {page_idx} out of range")
        
        doc_idx, page_num = self.pages[page_idx]
        doc = self.documents[doc_idx]
        
        # First check if we have exact DPI match
        exact_cached = self.cache.get(str(doc.filepath), page_num, target_dpi)
        if exact_cached:
            return exact_cached
        
        # Try to find cached image at any DPI
        # Prefer closest DPI to target
        common_dpis = [72, 96, 150, 200]
        best_cached = None
        best_dpi = None
        
        for dpi in sorted(common_dpis, key=lambda d: abs(d - target_dpi)):
            cached = self.cache.get(str(doc.filepath), page_num, dpi)
            if cached:
                best_cached = cached
                best_dpi = dpi
                break
        
        if best_cached and best_dpi != target_dpi:
            scale_factor = target_dpi / best_dpi
            
            # Only use rescaling if we're upscaling by less than 1.5x
            # Beyond that, quality degrades too much and we should render fresh
            if scale_factor <= 1.5:
                # Fast rescale with BILINEAR - acceptable quality
                new_size = (int(best_cached.width * scale_factor), int(best_cached.height * scale_factor))
                return best_cached.resize(new_size, Image.Resampling.BILINEAR)
            else:
                # Need much higher resolution - render fresh to avoid blurriness
                return self.get_page_thumbnail(page_idx, target_dpi)
        elif best_cached:
            return best_cached
        else:
            # No cache, render normally
            return self.get_page_thumbnail(page_idx, target_dpi)
    
    def select_page(self, page_idx: int, multi: bool = False):
        """
        Select page(s)
        
        Args:
            page_idx: Page index to select
            multi: If True, add to selection; if False, replace selection
        """
        if not multi:
            self.selected_pages.clear()
        
        self.selected_pages.add(page_idx)
        log.debug(f"Selected pages: {sorted(self.selected_pages)}")
    
    def select_range(self, start_idx: int, end_idx: int):
        """Select range of pages"""
        for idx in range(min(start_idx, end_idx), max(start_idx, end_idx) + 1):
            if 0 <= idx < len(self.pages):
                self.selected_pages.add(idx)
        log.debug(f"Selected range {start_idx}-{end_idx}")
    
    def deselect_all(self):
        """Deselect all pages"""
        self.selected_pages.clear()
    
    def select_all(self):
        """Select all pages (excluding Borrados section)"""
        all_pages = set(range(len(self.pages)))
        
        # Exclude pages in Borrados section if section_manager is available
        if self.section_manager:
            deleted_pages = set()
            for section in self.section_manager.sections:
                if section.is_special:  # Borrados section
                    deleted_pages = set(range(section.start_page, section.start_page + section.page_count))
                    break
            self.selected_pages = all_pages - deleted_pages
        else:
            self.selected_pages = all_pages
    
    def toggle_selection(self):
        """Toggle between select all and deselect all (excluding Borrados)"""
        if self.selected_pages:
            # If any pages selected, deselect all
            self.selected_pages.clear()
        else:
            # If no pages selected, select all (excluding Borrados)
            self.select_all()
    
    def is_selected(self, page_idx: int) -> bool:
        """Check if page is selected"""
        return page_idx in self.selected_pages
    
    def move_to_deleted_section(self, page_indices: List[int] = None):
        """
        Move pages to the 'Borrados' section (soft delete)
        If page_indices is None, uses selected_pages
        """
        if page_indices is None:
            if not self.selected_pages:
                return
            page_indices = sorted(self.selected_pages, reverse=True)
        else:
            page_indices = sorted(page_indices, reverse=True)
        
        # Extract pages from their current positions
        deleted_pages = []
        for page_idx in page_indices:
            page_info = self.pages[page_idx]
            deleted_pages.insert(0, page_info)  # Insert at beginning to maintain order
            del self.pages[page_idx]
        
        # Append to end (they will be in the 'Borrados' section)
        self.pages.extend(deleted_pages)
        
        # Clear selection and update marked pages indices
        self.selected_pages.clear()
        # Recalculate marked_pages indices (they may have shifted)
        new_marked = set()
        for old_idx in self.marked_pages:
            if old_idx not in page_indices:
                # Calculate new index
                shift = sum(1 for del_idx in page_indices if del_idx < old_idx)
                new_idx = old_idx - shift
                new_marked.add(new_idx)
        self.marked_pages = new_marked
        
        log.info(f"Moved {len(page_indices)} pages to Borrados section")
    
    def delete_selected_pages(self):
        """Move selected pages to 'Borrados' section (soft delete)"""
        self.move_to_deleted_section()
        
    def delete_pages(self, page_indices: List[int]):
        """
        Permanently delete pages from the viewer
        
        Args:
            page_indices: List of global page indices to delete
        """
        if not page_indices:
            return
            
        # Sort indices in reverse order to remove from end first
        # This keeps lower indices valid while removing
        sorted_indices = sorted(page_indices, reverse=True)
        
        for idx in sorted_indices:
            if 0 <= idx < len(self.pages):
                del self.pages[idx]
        
        # Clear/Update selections after deletion
        # Indices have shifted, so clearing selection is safest
        # Ideally we would map selection to new indices but for deletion 
        # that might be confusing if selected page was deleted.
        self.selected_pages.clear()
        self.marked_pages.clear()  # Clear marked pages to avoid index mismatch
        log.info(f"Permanently deleted {len(page_indices)} pages")
    
    def move_pages(self, page_indices: List[int], target_idx: int) -> bool:
        """
        Move pages to a new position
        
        Args:
            page_indices: List of page indices to move (must be sorted)
            target_idx: Target position to move pages to
            
        Returns:
            True if successful
        """
        if not page_indices:
            return False
        
        # Ensure indices are sorted
        page_indices = sorted(page_indices)
        
        # Validate indices
        if any(idx < 0 or idx >= len(self.pages) for idx in page_indices):
            log.error("Invalid page indices for move")
            return False
        
        if target_idx < 0 or target_idx > len(self.pages):
            log.error("Invalid target index for move")
            return False
        
        # Extract pages to move
        pages_to_move = [self.pages[idx] for idx in page_indices]
        
        # Remove pages from original positions (in reverse order to maintain indices)
        for idx in reversed(page_indices):
            self.pages.pop(idx)
        
        # Adjust target index if needed
        # If target is after removed pages, need to adjust
        adjusted_target = target_idx
        for idx in page_indices:
            if idx < target_idx:
                adjusted_target -= 1
        
        # Insert pages at new position
        for i, page in enumerate(pages_to_move):
            self.pages.insert(adjusted_target + i, page)
        
        # Update selection to new positions
        new_selection = set(range(adjusted_target, adjusted_target + len(pages_to_move)))
        self.selected_pages = new_selection
        
        log.info(f"Moved {len(page_indices)} pages to position {adjusted_target}")
        return True
    
    def save_subset(self, output_path: str, page_indices: List[int], garbage: int = 4, deflate: bool = True, silent: bool = False, remove_signatures: bool = False):
        """
        Save subset of pages (by global index) to a new PDF file
        
        Args:
            output_path: Output file path
            page_indices: List of global page indices to include
            garbage: Garbage collection level
            deflate: Use deflate compression
            silent: If True, don't log (for temporary files)
            remove_signatures: If True, remove signature fields from the output
        """
        import fitz
        
        if not page_indices:
            return
            
        result = fitz.open()
        
        for idx in page_indices:
            if idx < 0 or idx >= len(self.pages):
                continue
                
            doc_idx, page_num = self.pages[idx]
            src_doc = self.documents[doc_idx].doc
            
            # Insert page
            # Note: insert_pdf copies resources. 
            # For single page:
            result.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
            
        # Remove signatures if requested
        if remove_signatures:
            removed_count = 0
            for page in result:
                # Iterate over all widgets (form fields)
                for widget in page.widgets():
                    if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                        page.delete_widget(widget)
                        removed_count += 1
            
            if removed_count > 0 and not silent:
                log.info(f"Removed {removed_count} signature fields from {output_path}")
            
        try:
            result.save(output_path, garbage=garbage, deflate=deflate)
        except Exception as e:
            err_str = str(e).lower()
            # Mitigación específica para PDFs con estructura AcroForm rota (ej. algunos PORTAFIRMAS/COPIA AUTÉNTICA).
            if "cycle" in err_str or "structure" in err_str or "code=7" in err_str:
                removed_widgets = 0
                # Eliminamos TODOS los widgets del resultado (no solo firmas) para romper ciclos de parents corruptos.
                for page in result:
                    widgets = list(page.widgets() or [])
                    for widget in widgets:
                        try:
                            page.delete_widget(widget)
                            removed_widgets += 1
                        except Exception:
                            pass

                if not silent:
                    log.warning(
                        f"save_subset fallback activado por error estructural: "
                        f"se eliminaron {removed_widgets} widgets para reintentar guardado de {output_path}"
                    )

                # Reintento conservador: menos agresivo en garbage para maximizar compatibilidad.
                result.save(output_path, garbage=1, deflate=deflate)
            else:
                raise
        finally:
            result.close()
        
        if not silent:
            log.info(f"Saved subset of {len(page_indices)} pages to {output_path}")

    def save_pages_direct(self, output_path: str, page_list: List[tuple], garbage: int = 4, deflate: bool = True, silent: bool = False, remove_signatures: bool = False):
        """
        Save list of specific pages [(doc_idx, page_num)] to a new PDF
        Useful when global indices are not available or relevant (e.g. Box Mode / custom lists)
        """
        import fitz
        
        if not page_list:
            return
            
        result = fitz.open()
        
        try:
            for doc_idx, page_num in page_list:
                if 0 <= doc_idx < len(self.documents):
                    src_doc = self.documents[doc_idx].doc
                    result.insert_pdf(src_doc, from_page=page_num, to_page=page_num)

            # Eliminar firmas si está activado.
            # Esto asegura que cualquier PDF generado para exportación/subida salga sin
            # campos de firma digital, igual que en save_subset().
            if remove_signatures:
                removed_count = 0
                for page in result:
                    for widget in page.widgets():
                        if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                            page.delete_widget(widget)
                            removed_count += 1

                if removed_count > 0 and not silent:
                    log.info(f"Removed {removed_count} signature fields from {output_path}")
            
            result.save(output_path, garbage=garbage, deflate=deflate)
        finally:
            result.close()
            
        if not silent:
            log.info(f"Saved direct list of {len(page_list)} pages to {output_path}")

    def diagnose_save_error_paths(self, file_paths: List[str]) -> str | None:
        """
        Lógica central de diagnóstico: Fusión Incremental.
        Si los archivos individuales no fallan, el error surge al combinarlos.
        Recreamos la fusión paso a paso para ver quién rompe la cadena.
        """
        import fitz
        import tempfile
        import os
        from pathlib import Path
        
        # Mantener orden y unicidad (Python 3.7+ dict mantiene orden de inserción)
        unique_paths = list(dict.fromkeys(p for p in file_paths if p and os.path.exists(p)))
        count = len(unique_paths)
        log.info(f"Diagnosing save error via Incremental Merge among {count} files...")
        
        # Crear documento acumulativo para simular la fusión real
        merged_doc = fitz.open()
        
        for i, filepath in enumerate(unique_paths):
            log.info(f"Diagnostic step {i+1}/{count}: Adding {Path(filepath).name}")
            
            try:
                # 1. Intentar añadir el archivo al acumulado
                with fitz.open(filepath) as src_doc:
                    merged_doc.insert_pdf(src_doc)
                
                # 2. Intentar guardar el estado actual (aquí es donde esperamos que explote)
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp_name = tmp.name
                
                try:
                    # Usamos garbage=4 y deflate=True para forzar reestructuración completa, igual que el guardado real
                    merged_doc.save(tmp_name, garbage=4, deflate=True)
                except Exception as save_err:
                    err_str = str(save_err).lower()
                    log.error(f"Diagnostic caught error after adding {Path(filepath).name}: {save_err}")
                    
                    # Si falla al guardar justo después de añadir este archivo, este es el culpable (o el detonante)
                    if "cycle" in err_str or "structure" in err_str or "code=7" in err_str or "trailer" in err_str:
                        merged_doc.close()
                        return str(filepath)
                    
                    # Si es otro error, también lo consideramos sospechoso
                    merged_doc.close()
                    return str(filepath)
                    
            except Exception as e:
                log.error(f"Error processing {filepath} during diagnostic: {e}")
                merged_doc.close()
                return str(filepath)
            finally:
                if 'tmp_name' in locals() and tmp_name and os.path.exists(tmp_name):
                    try: os.unlink(tmp_name)
                    except: pass

        merged_doc.close()
        log.warning("Incremental diagnostic finished without reproducing the error.")
        return None

    def diagnose_save_error(self, page_indices: List[int], remove_signatures: bool = False) -> str | None:
        """Diagnostica desde índices globales (Modo Visor) replicando save_subset por páginas."""
        import fitz
        import tempfile
        import os

        # Normalizamos índices válidos conservando el orden real de guardado.
        valid_page_indices = [idx for idx in page_indices if 0 <= idx < len(self.pages)]
        if not valid_page_indices:
            return None

        # Mapa auxiliar para logs: cuántos PDFs participan en este guardado.
        involved_paths = []
        seen_paths = set()
        for idx in valid_page_indices:
            doc_idx, _ = self.pages[idx]
            if 0 <= doc_idx < len(self.documents):
                p = str(self.documents[doc_idx].filepath)
                if p not in seen_paths:
                    seen_paths.add(p)
                    involved_paths.append(p)

        log.info(
            f"Diagnosing save error in-memory by selected pages: "
            f"{len(valid_page_indices)} pages / {len(involved_paths)} files"
        )

        # Réplica fiel: insertamos página a página (igual que save_subset) y probamos guardado incremental.
        result = fitz.open()
        try:
            for step, global_idx in enumerate(valid_page_indices, 1):
                doc_idx, page_num = self.pages[global_idx]
                if not (0 <= doc_idx < len(self.documents)):
                    continue

                src_obj = self.documents[doc_idx]
                src_doc = src_obj.doc
                src_path = str(src_obj.filepath)

                try:
                    result.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
                except Exception as e:
                    log.error(f"Diagnostic in-memory insert failed at step {step} for {src_path}: {e}")
                    return src_path

                tmp_name = None
                test_doc = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp_name = tmp.name

                    # Si el guardado real quita firmas, lo replicamos aquí para evitar falsos negativos.
                    if remove_signatures:
                        pdf_bytes = result.tobytes()
                        test_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                        for page in test_doc:
                            for widget in page.widgets():
                                if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                                    page.delete_widget(widget)
                        test_doc.save(tmp_name, garbage=4, deflate=True)
                    else:
                        result.save(tmp_name, garbage=4, deflate=True)

                except Exception as save_err:
                    err_str = str(save_err).lower()
                    log.error(
                        f"Diagnostic in-memory save failed at step {step} "
                        f"(file={Path(src_path).name}, page={page_num + 1}): {save_err}"
                    )
                    if "cycle" in err_str or "structure" in err_str or "code=7" in err_str or "trailer" in err_str:
                        return src_path
                    return src_path
                finally:
                    if test_doc is not None:
                        try:
                            test_doc.close()
                        except Exception:
                            pass
                    if tmp_name and os.path.exists(tmp_name):
                        try:
                            os.unlink(tmp_name)
                        except Exception:
                            pass
        finally:
            result.close()

        # Fallback conservador por rutas para no perder trazabilidad si no reproduce en memoria.
        return self.diagnose_save_error_paths(involved_paths)

    def diagnose_save_error_refs(self, refs: List) -> str | None:
        """Diagnostica desde PageReference objects (Modo Cajas) - Preservando orden"""
        from src.pdf.structure import PageReference
        paths = []
        seen = set()
        for r in refs:
            if isinstance(r, PageReference) and r.file_path:
                if r.file_path not in seen:
                    paths.append(r.file_path)
                    seen.add(r.file_path)
        return self.diagnose_save_error_paths(paths)
    
    def rotate_selected_pages(self, rotation: int = 90):
        """
        Rotate selected pages
        
        Args:
            rotation: Rotation in degrees (90, 180, 270)
        """
        if not self.selected_pages:
            return
        
        for page_idx in self.selected_pages:
            doc_idx, page_num = self.pages[page_idx]
            doc = self.documents[doc_idx]
            
            doc.rotate_page(page_num, rotation)
            
            # Clear cache for this PDF to force re-render
            self.cache.clear_pdf(str(doc.filepath))
        
        log.info(f"Rotated {len(self.selected_pages)} pages by {rotation}°")
    
    def insert_blank_pages(self):
        """
        Insert blank pages after selection (or at end if nothing selected)
        """
        import fitz
        
        # Determine insertion point
        if self.selected_pages:
            # Insert after last selected page
            selected = sorted(self.selected_pages)
            insert_at = selected[-1] + 1
            count = len(selected)
        else:
            # Insert at end
            insert_at = len(self.pages)
            count = 1
        
        # Get dimensions from a reference page (use first page or A4 default)
        if self.pages:
            # Use dimensions from the page before insertion point
            ref_idx = min(insert_at - 1, len(self.pages) - 1) if insert_at > 0 else 0
            doc_idx, page_num = self.pages[ref_idx]
            doc = self.documents[doc_idx]
            width, height = doc.get_page_size(page_num)
        else:
            # Default A4 size
            width, height = 595, 842
        
        # Insert blank pages
        new_pages = []
        for _ in range(count):
            # Use the document of the last page, or first document
            if insert_at > 0 and insert_at <= len(self.pages):
                doc_idx, _ = self.pages[insert_at - 1]
            elif self.documents:
                doc_idx = 0
            else:
                log.warning("No documents loaded, cannot insert blank page")
                return
            
            doc = self.documents[doc_idx]
            
            # Insert blank page at end of document
            doc.insert_page(doc.page_count, width, height)
            new_page_num = doc.page_count - 1
            
            new_pages.append((doc_idx, new_page_num))
        
        # Insert new pages into our pages list
        for i, new_page in enumerate(new_pages):
            self.pages.insert(insert_at + i, new_page)
        
        # Update selection to the new blank pages
        self.selected_pages = set(range(insert_at, insert_at + len(new_pages)))
        
        log.info(f"Inserted {len(new_pages)} blank page(s)")
    
    def duplicate_selected_pages(self):
        """
        Duplicate selected pages (insert copies after the last selected page)
        """
        if not self.selected_pages:
            return
        
        import fitz
        
        # Sort selected pages
        selected = sorted(self.selected_pages)
        
        # Find insertion point (after last selected page)
        insert_at = selected[-1] + 1
        
        # Group by document to handle page number shifts
        pages_by_doc = {}
        for page_idx in selected:
            doc_idx, page_num = self.pages[page_idx]
            if doc_idx not in pages_by_doc:
                pages_by_doc[doc_idx] = []
            pages_by_doc[doc_idx].append((page_idx, page_num))
        
        # Create copies for each document
        new_pages = []
        for doc_idx, doc_pages in pages_by_doc.items():
            doc = self.documents[doc_idx]
            
            # Sort by page_num to maintain order
            doc_pages.sort(key=lambda x: x[1])
            
            for page_idx, page_num in doc_pages:
                # Create a temporary document to copy the page
                temp_doc = fitz.open()
                temp_doc.insert_pdf(doc.doc, from_page=page_num, to_page=page_num)
                
                # Insert at the end of the document
                doc.doc.insert_pdf(temp_doc, from_page=0, to_page=0)
                
                # Close temp document
                temp_doc.close()
                
                # Get the new page number (last page)
                new_page_num = doc.page_count - 1
                
                new_pages.append((doc_idx, new_page_num))
        
        # Insert new pages into our pages list at the correct position
        for i, new_page in enumerate(new_pages):
            self.pages.insert(insert_at + i, new_page)
        
        # Update selection to the new pages
        self.selected_pages = set(range(insert_at, insert_at + len(new_pages)))
        
        log.info(f"Duplicated {len(selected)} pages")
    
    def mark_selected_as_blank(self):
        """
        Mark selected pages as blank (for later deletion)
        Automatically detects which pages in selection are actually blank
        """
        if not self.selected_pages:
            return
        
        # Detect which selected pages are actually blank
        newly_marked = []
        for page_idx in self.selected_pages:
            if page_idx not in self.marked_pages:  # Don't re-check already marked
                doc_idx, page_num = self.pages[page_idx]
                doc = self.documents[doc_idx]
                
                # Check if page is blank
                if doc.is_page_blank(page_num):
                    self.marked_pages.add(page_idx)
                    newly_marked.append(page_idx)
        
        log.info(f"Marked {len(newly_marked)} blank pages out of {len(self.selected_pages)} selected")
    
    def unmark_selected(self):
        """
        Unmark selected pages
        """
        if not self.selected_pages:
            return
        
        # Remove selected pages from marked set
        unmarked = self.selected_pages & self.marked_pages
        self.marked_pages -= self.selected_pages
        
        log.info(f"Unmarked {len(unmarked)} pages")
    
    def delete_marked_pages(self):
        """
        Delete all marked pages (move to 'Borrados' section)
        """
        if not self.marked_pages:
            return
        
        # Move marked pages to deleted section
        marked_list = list(self.marked_pages)
        self.move_to_deleted_section(marked_list)
        
        # Clear marked pages
        self.marked_pages.clear()
        
        log.info(f"Moved {len(marked_list)} marked pages to Borrados")
    
    def is_marked(self, page_idx: int) -> bool:
        """Check if page is marked as blank"""
        return page_idx in self.marked_pages
    
    def set_zoom(self, zoom_pct: int):
        """Set zoom level (50-200%)"""
        self.current_zoom = max(50, min(200, zoom_pct))
        log.debug(f"Zoom set to {self.current_zoom}%")
    
    def get_render_dpi(self) -> int:
        """Get DPI for current zoom level"""
        # Base DPI is 72, scale by zoom
        return int(72 * self.current_zoom / 100)
    
    def close_all(self):
        """Close all documents"""
        for doc in self.documents:
            doc.close()
        self.documents.clear()
        self.pages.clear()
        self.selected_pages.clear()
        self.marked_pages.clear()
        self.cache.clear()
        # Limpiar caché de documentos por ruta
        if hasattr(self, '_doc_by_path'):
            self._doc_by_path.clear()
        log.info("Closed all documents")
    
    def load_from_page_refs(self, refs: List[PageReference]) -> int:
        """
        Carga páginas desde una lista de PageReference.
        
        Abre los documentos necesarios (cacheando por ruta para evitar duplicados)
        y añade las páginas al viewer en el orden especificado.
        
        Args:
            refs: Lista de PageReference con las páginas a cargar
            
        Returns:
            Número de páginas cargadas exitosamente
        """
        if not refs:
            return 0
        
        # Caché de documentos abiertos por ruta (evita abrir el mismo PDF múltiples veces)
        if not hasattr(self, '_doc_by_path'):
            self._doc_by_path = {}
        
        loaded_count = 0
        
        for ref in refs:
            try:
                # Obtener o abrir el documento
                if ref.file_path not in self._doc_by_path:
                    # Abrir nuevo documento
                    doc = PdfDocument(ref.file_path)
                    doc_idx = len(self.documents)
                    self.documents.append(doc)
                    self._doc_by_path[ref.file_path] = doc_idx
                    log.debug(f"Opened document for PageRef: {ref.file_path} -> doc_idx={doc_idx}")
                else:
                    doc_idx = self._doc_by_path[ref.file_path]

                # Validación defensiva: si el índice no existe en el PDF real,
                # ignoramos el PageReference obsoleto en vez de romper la expansión.
                doc = self.documents[doc_idx]
                if not (0 <= ref.page_index < doc.page_count):
                    log.warning(
                        "Skipping stale PageReference %s: page_index=%s out of range (0-%s)",
                        ref,
                        ref.page_index,
                        max(0, doc.page_count - 1),
                    )
                    continue
                
                # Añadir la página
                self.pages.append((doc_idx, ref.page_index))
                loaded_count += 1
                
            except Exception as e:
                log.error(f"Error loading page from {ref}: {e}")
        
        log.info(f"Loaded {loaded_count} pages from {len(self._doc_by_path)} documents via PageReference")
        return loaded_count
    
    def get_page_refs_for_range(self, start_idx: int, end_idx: int) -> List[PageReference]:
        """
        Convierte un rango de páginas del viewer a PageReference.
        
        Útil para crear cajas desde secciones existentes.
        
        Args:
            start_idx: Índice inicial (inclusive)
            end_idx: Índice final (exclusive)
            
        Returns:
            Lista de PageReference
        """
        refs = []
        for page_idx in range(start_idx, min(end_idx, len(self.pages))):
            doc_idx, page_num = self.pages[page_idx]
            if doc_idx < len(self.documents):
                doc = self.documents[doc_idx]
                refs.append(PageReference(
                    file_path=str(doc.filepath),
                    page_index=page_num
                ))
        return refs
    
    def render_page_ref_thumbnail(self, ref: PageReference, dpi: int = 72) -> Image.Image:
        """
        Renderiza una miniatura desde un PageReference sin añadirla al viewer.
        
        Útil para generar thumbnails de cajas sin cargar todas las páginas.
        
        Args:
            ref: PageReference de la página a renderizar
            dpi: Resolución de la miniatura
            
        Returns:
            PIL Image de la miniatura
        """
        # Verificar caché primero
        cached = self.cache.get(ref.file_path, ref.page_index, dpi)
        if cached:
            return cached
        
        # Abrir documento temporalmente si no está en el viewer
        doc = None
        close_after = False
        
        # Buscar si ya tenemos el documento abierto
        if hasattr(self, '_doc_by_path') and ref.file_path in self._doc_by_path:
            doc_idx = self._doc_by_path[ref.file_path]
            doc = self.documents[doc_idx]
        else:
            # Buscar en documents por filepath
            for d in self.documents:
                if str(d.filepath) == ref.file_path:
                    doc = d
                    break
        
        if not doc:
            # Abrir temporalmente
            doc = PdfDocument(ref.file_path)
            close_after = True
        
        try:
            # Renderizar
            image = doc.render_page_thumbnail(ref.page_index, dpi=dpi)
            # Cachear
            self.cache.put(ref.file_path, ref.page_index, dpi, image)
            return image
        finally:
            if close_after:
                doc.close()
