"""csvq — query CSV files with a SQL subset. Zero dependencies."""

from .engine import QueryError, run_query
from .infer import load_table
from .parser import parse
from .tokenize import SQLError, tokenize

__version__ = "1.0.0"
__all__ = [
    "QueryError", "SQLError", "run_query", "parse", "tokenize",
    "load_table", "__version__",
]
