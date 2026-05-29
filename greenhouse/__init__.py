"""Modular Greenhouse configuration & engineering-triage engine.

Public API:
    from greenhouse import Catalog, build_layout, configure, assess, build_quote
"""

from .catalog import Catalog, CatalogError
from .configurator import Configuration, BomLine, configure, footprint_sqft
from .engineering import EngineeringCheck, assess
from .models import Layout, Run, Junction, build_layout, shape_options, SHAPE_INFO
from .quote import Quote, QuoteLine, build_quote

__all__ = [
    "Catalog",
    "CatalogError",
    "Configuration",
    "BomLine",
    "configure",
    "footprint_sqft",
    "EngineeringCheck",
    "assess",
    "Layout",
    "Run",
    "Junction",
    "build_layout",
    "shape_options",
    "SHAPE_INFO",
    "Quote",
    "QuoteLine",
    "build_quote",
]

__version__ = "0.1.0"
