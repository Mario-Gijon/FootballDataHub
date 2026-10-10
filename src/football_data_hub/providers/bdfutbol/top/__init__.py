"""Captura y normalización de Destacados de BDFutbol."""

from .models import ParsedTop
from .parser import TopParseError, parse_top_page

__all__ = ["ParsedTop", "TopParseError", "parse_top_page"]
