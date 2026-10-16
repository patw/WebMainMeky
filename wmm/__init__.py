"""WebMainMeky - main-content extraction service.

Request path: deterministic. LLM: rule authoring only, off the hot path.
"""
from .pipeline import extract

__all__ = ['extract']
__version__ = "0.4.0"
