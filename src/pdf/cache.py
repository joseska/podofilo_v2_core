"""
PDF Page Cache - Thumbnail caching with LRU
Replaces cache.py with modern implementation
"""
import logging
from typing import Dict, Optional
from PIL import Image
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

class PageCache:
    """LRU cache for PDF page thumbnails"""
    
    def __init__(self, max_size: int = 100):
        """
        Initialize cache
        
        Args:
            max_size: Maximum number of cached thumbnails
        """
        self.max_size = max_size
        self._cache: Dict[str, Image.Image] = {}
        self._access_order = []
    
    def _make_key(self, pdf_path: str, page_num: int, dpi: int) -> str:
        """Create cache key"""
        return f"{pdf_path}:{page_num}:{dpi}"
    
    def get(self, pdf_path: str, page_num: int, dpi: int) -> Optional[Image.Image]:
        """Get cached thumbnail"""
        key = self._make_key(pdf_path, page_num, dpi)
        
        if key in self._cache:
            # Move to end (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        
        return None
    
    def put(self, pdf_path: str, page_num: int, dpi: int, image: Image.Image):
        """Cache thumbnail"""
        key = self._make_key(pdf_path, page_num, dpi)
        
        # Remove oldest if cache is full
        if len(self._cache) >= self.max_size and key not in self._cache:
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]
            log.debug(f"Evicted {oldest_key} from cache")
        
        # Add/update cache
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
        self._cache[key] = image
        
        log.debug(f"Cached {key} ({len(self._cache)}/{self.max_size})")
    
    def clear(self):
        """Clear entire cache"""
        self._cache.clear()
        self._access_order.clear()
        log.info("Cache cleared")
    
    def clear_pdf(self, pdf_path: str):
        """Clear all pages for a specific PDF"""
        keys_to_remove = [k for k in self._cache.keys() if k.startswith(f"{pdf_path}:")]
        for key in keys_to_remove:
            del self._cache[key]
            self._access_order.remove(key)
        log.debug(f"Cleared {len(keys_to_remove)} pages for {pdf_path}")

# Global cache instance - Increased for large documents (200+ pages)
_global_cache = PageCache(max_size=500)

def get_cache() -> PageCache:
    """Get global cache instance"""
    return _global_cache
