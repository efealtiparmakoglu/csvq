"""Command line entry point."""

import argparse
import sys
from pathlib import Path

from . import __version__
from .engine import QueryError, Engine
from .infer import SQLErrorIO
from .output import format_output
from .parser import parse
from .tokenize import SQLError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csvq",
        description="Query CSV files with a SQL subset: WHERE, JOIN, "
        "GROUP BY, aggregates, ORDER BY — with type inference and several "
        "output formats. Zero dependencies.",
    )
    parser.add_argument("query", help="SQL query; table names are CSV file paths")
    parser.add_argument("-f", "--format", default="table",
                        choices=("table", "csv", "tsv", "json", "markdown"),
                        help="output format (default: table)")
    parser.add_argument("-d", "--delimiter", default=",",
                        help="input field delimiter (default ,)")
    parser.add_argument("--no-header", action="store_true",
                        help="input files have no header row (columns named col1..)")
    parser.add_argument("-V", "--version", action="version",
                        version=f"csvq {__version__}")
    return parser


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        select = parse(args.query)
        engine = Engine(delimiter=args.delimiter, no_header=args.no_header,
                        base_dir=Path.cwd())
        columns, rows = engine.run(select)
        print(format_output(args.format, columns, rows, delimiter=args.delimiter))
        return 0
    except SQLError as exc:
        print(f"csvq: syntax error: {exc}", file=sys.stderr)
        return 2
    except SQLErrorIO as exc:
        print(f"csvq: {exc}", file=sys.stderr)
        return 1
    except QueryError as exc:
        print(f"csvq: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, IsADirectoryError) as exc:
        print(f"csvq: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"csvq: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
