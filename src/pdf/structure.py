from dataclasses import dataclass, field
from typing import List, Optional, Callable
from enum import Enum
from pathlib import Path
import asyncio
import re

@dataclass
class Section:
    """Logical document section"""
    id: str
    title: str
    start_page: int  # 0-indexed absolute page number
    page_count: int
    # Split configuration: (value, type) where type is 'p' (pages) or 'b' (bytes)
    # e.g. (6, 'p') for /6p, (5242880, 'b') for /5M
    split_config: Optional[tuple] = None
    # Special flag for sections that should not be saved (like "Borrados")
    is_special: bool = False 
    metadata: dict = field(default_factory=dict)    
    @property
    def end_page(self) -> int:
        return self.start_page + self.page_count

class SectionManager:
    """Manages document sections"""
    def __init__(self):
        self.sections: List[Section] = []
        
    def _ensure_deleted_section(self):
        """Ensure the special 'Borrados' section exists at the end"""
        # Check if deleted section exists
        if not self.sections or self.sections[-1].id != "deleted":
            # Calculate start page (after all other sections)
            start_page = 0
            if self.sections:
                last_section = self.sections[-1]
                start_page = last_section.start_page + last_section.page_count
            
            deleted_section = Section(
                id="deleted",
                title="Borrados",
                start_page=start_page,
                page_count=0,
                is_special=True
            )
            self.sections.append(deleted_section)
    
    def get_deleted_section(self) -> Section:
        """Get the special 'Borrados' section"""
        self._ensure_deleted_section()
        return self.sections[-1]
    
    def get_saveable_sections(self) -> List[Section]:
        """Get only sections that should be saved (excludes special sections AND empty sections)"""
        return [s for s in self.sections if not s.is_special and s.page_count > 0]
    
    def initialize_default(self, total_pages: int, base_name: str = "resultado"):
        """Initialize with a single section covering all pages"""
        # Remove old deleted section if exists
        self.sections = [s for s in self.sections if not s.is_special]
        
        # Create default section
        self.sections = [
            Section(id="default", title=base_name, start_page=0, page_count=total_pages)
        ]
    
    def get_section_at(self, page_index: int) -> Optional[Section]:
        """Get section containing page index"""
        for section in self.sections:
            if section.start_page <= page_index < section.end_page:
                return section
        return None
        
    def _split_base_number(self, title: str) -> tuple[str, Optional[int]]:
        """Return (base_name, numeric_suffix) ignoring split configs."""
        base = re.sub(r'/\d+[pPbBmMkK]$', '', title).strip()
        number = None
        if '_' in base:
            prefix, suffix = base.rsplit('_', 1)
            if suffix.isdigit():
                base = prefix
                number = int(suffix)
        return base or "resultado", number

    def _generate_next_title(self, base_name: str = "resultado") -> str:
        """Generate next unique title based on pattern base_name_N"""
        normalized_base = base_name.strip() or "resultado"
        existing_nums = []
        for s in self.sections:
            s_base, s_num = self._split_base_number(s.title)
            if s_base == normalized_base:
                existing_nums.append(s_num or 1)
        
        next_num = 1
        if existing_nums:
            next_num = max(existing_nums) + 1
            
        if next_num == 1:
             return normalized_base
        
        return f"{normalized_base}_{next_num}"

    def split_section(self, page_index: int, new_title: str = None, base_name: Optional[str] = None):
        """Split section at page_index (starts new section)"""
        # Find section containing page_index
        target_section_idx = -1
        for i, section in enumerate(self.sections):
            if section.start_page <= page_index < section.end_page:
                target_section_idx = i
                break
                
        if target_section_idx == -1:
            return
            
        original = self.sections[target_section_idx]
        
        # Cannot split at start of section
        if page_index == original.start_page:
            return
            
        # Calculate split point
        split_offset = page_index - original.start_page
        new_count = original.page_count - split_offset
        
        # Update original
        original.page_count = split_offset
        
        # Determine base name for new title
        if base_name:
            normalized_base = self._split_base_number(base_name)[0]
        else:
            normalized_base = self._split_base_number(original.title)[0]
        
        # Determine title
        if new_title is None:
            new_title = self._generate_next_title(normalized_base)

        # Create new section
        new_section = Section(
            id=f"sec_{page_index}", 
            title=new_title,
            start_page=page_index,
            page_count=new_count
        )
        
        self.sections.insert(target_section_idx + 1, new_section)

    def merge_section_up(self, section_index: int):
        """Merge section with previous one"""
        if section_index <= 0 or section_index >= len(self.sections):
            return
            
        prev = self.sections[section_index - 1]
        curr = self.sections[section_index]
        
        prev.page_count += curr.page_count
        self.sections.pop(section_index)
        
    def set_split_config(self, section_index: int, val: int, type_: str):
        """Set split configuration for a section"""
        if 0 <= section_index < len(self.sections):
            section = self.sections[section_index]
            section.split_config = (val, type_)
            
            # Update title to reflect config (remove old suffix if any)
            import re
            base_title = re.sub(r'/\d+[pPbBmMkK]$', '', section.title)
            
            if type_ == 'p':
                section.title = f"{base_title}/{val}p"
            elif type_ == 'b':
                # Convert bytes to M or K for display
                if val >= 1024*1024:
                    display_val = f"{val//(1024*1024)}M"
                elif val >= 1024:
                    display_val = f"{val//1024}k"
                else:
                    display_val = f"{val}b"
                section.title = f"{base_title}/{display_val}"
                
    def rename_section(self, section_index: int, new_title: str):
        """Rename section and parse split config from title"""
        if 0 <= section_index < len(self.sections):
            section = self.sections[section_index]
            section.title = new_title
            
            # Parse config from title
            import re
            # Pattern: /digits(p|m|k|b) case insensitive at end of string
            # Group 1: digits
            # Group 2: unit
            match = re.search(r'/(\d+)([pPbBmMkK])$', new_title)
            if match:
                val = int(match.group(1))
                unit = match.group(2).lower()
                
                if unit == 'p':
                    section.split_config = (val, 'p')
                elif unit == 'm':
                    section.split_config = (val * 1024 * 1024, 'b')
                elif unit == 'k':
                    section.split_config = (val * 1024, 'b')
                elif unit == 'b':
                    section.split_config = (val, 'b')
            else:
                # If no suffix, clear config?
                # User might want to remove split by removing suffix.
                # So yes, clear it.
                section.split_config = None


# ============================================================================
# DOCUMENT BOX SYSTEM (Staging Area)
# ============================================================================

class BoxState(Enum):
    """State of a document box"""
    LOADING = "loading"      # Currently loading/downloading
    LOADED = "loaded"        # Successfully loaded, ready to expand
    FAILED = "failed"        # Failed to load
    QUEUED = "queued"        # Queued for retry
    CANCELLED = "cancelled"  # User cancelled
    MARKED = "marked"        # Marked to be ignored


@dataclass(eq=False)
class DocumentBox:
    """
    Base class for document boxes (staging area).
    Represents a document that hasn't been expanded into individual pages yet.
    """
    name: str
    state: BoxState = BoxState.LOADING
    pages: List = field(default_factory=list)  # Empty until loaded
    thumbnail: Optional[object] = None  # PIL Image of first page
    progress: float = 0.0  # 0.0 to 1.0
    future: Optional[asyncio.Future] = None
    metadata: dict = field(default_factory=dict)
    error_message: str = ""
    
    def is_expanded(self) -> bool:
        """Check if box has been expanded to pages"""
        return len(self.pages) > 0 and self.state == BoxState.LOADED
    
    def can_expand(self) -> bool:
        """Check if box is ready to be expanded"""
        return self.state == BoxState.LOADED and len(self.pages) > 0
    
    def mark_ignored(self):
        """Mark this box to be ignored"""
        self.state = BoxState.MARKED
    
    def unmark(self):
        """Unmark this box"""
        if self.state == BoxState.MARKED:
            self.state = BoxState.LOADED if self.pages else BoxState.LOADING
    
    def cancel(self):
        """Cancel loading operation"""
        if self.future and not self.future.done():
            self.future.cancel()
        self.state = BoxState.CANCELLED
    
    def set_failed(self, error_msg: str = ""):
        """Mark as failed"""
        self.state = BoxState.FAILED
        self.error_message = error_msg
    
    def set_loaded(self, pages: List):
        """Mark as successfully loaded"""
        self.pages = pages
        self.state = BoxState.LOADED
        self.progress = 1.0
        # Set thumbnail to first page if available
        if pages:
            # Generate static thumbnail immediately to avoid keeping fitz.Page reference in thumbnail
            first_page = pages[0]
            # Check for get_pixmap safe way (duck typing)
            if hasattr(first_page, 'get_pixmap'):
                 try:
                     # Use fitz to get pixmap
                     pix = first_page.get_pixmap(dpi=72)
                     # Convert to PIL Image
                     from PIL import Image
                     self.thumbnail = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                 except Exception:
                     # Fallback if conversion fails
                     self.thumbnail = None
            else:
                 # Assume it's already an image or None
                 self.thumbnail = first_page

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other


@dataclass(eq=False)
class LocalDocumentBox(DocumentBox):
    """Document box for local PDF files"""
    file_path: Path = None
    
    def __post_init__(self):
        if self.file_path:
            self.metadata['source'] = 'local'
            self.metadata['path'] = str(self.file_path)


@dataclass(eq=False)
class RemoteDocumentBox(DocumentBox):
    """Document box for remote downloads (OVE/ACEX)"""
    source: str = "unknown"  # 'ove' or 'acex'
    document_id: str = ""
    download_url: str = ""
    retries_left: int = 1  # Auto-retries allowed
    
    def __post_init__(self):
        self.metadata['source'] = self.source
        self.metadata['document_id'] = self.document_id
