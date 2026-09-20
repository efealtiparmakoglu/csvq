"""Type inference for CSV columns.

Every value starts as a string from the csv module. A column is inferred as
int, float, bool or NULL-able variants when every non-empty value matches;
empty strings become None for typed columns and stay "" for text columns.
"""

import csv
from dataclasses import dataclass


@dataclass
class Table:
    columns: list[str]
    rows: list[dict]  # column -> typed value

    def __len__(self) -> int:
        return len(self.rows)


def _as_bool(text: str) -> bool | None:
    low = text.strip().lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    return None


def _as_int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _as_float(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    # reject the string forms float() accepts but CSVs never mean (nan/inf)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def infer_type(values: list[str]) -> type | None:
    """Returns int, float, bool, or None (text/mixed)."""
    non_empty = [v for v in values if v != ""]
    if not non_empty:
        return None
    kinds = []
    for v in non_empty:
        if _as_int(v) is not None:
            kinds.append(int)
        elif _as_float(v) is not None:
            kinds.append(float)
        elif _as_bool(v) is not None:
            kinds.append(bool)
        else:
            return None
    if all(k is int for k in kinds):
        return int
    if all(k in (int, float) for k in kinds):
        return float
    if all(k is bool for k in kinds):
        return bool
    return None


def convert(text: str, kind: type | None):
    """Converts one raw string to the column's inferred type."""
    if kind is None:
        return text
    if text == "":
        return None
    if kind is int:
        return _as_int(text)
    if kind is float:
        return _as_float(text)
    if kind is bool:
        return _as_bool(text)
    return text


def load_table(path: str, delimiter: str = ",", has_header: bool = True) -> Table:
    """Reads a CSV file into a Table with inferred column types."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            rows = [row for row in reader if row]
    except OSError as exc:
        raise SQLErrorIO(f"cannot read {path!r}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise SQLErrorIO(f"{path!r} is not valid UTF-8: {exc}") from exc

    if not rows:
        return Table(columns=[], rows=[])

    if has_header:
        columns = [c.strip() for c in rows[0]]
        raw_rows = rows[1:]
    else:
        width = max(len(r) for r in rows)
        columns = [f"col{i + 1}" for i in range(width)]
        raw_rows = rows

    # normalize widths
    width = len(columns)
    raw_rows = [r + [""] * (width - len(r)) if len(r) < width else r[:width] for r in raw_rows]

    kinds = [
        infer_type([row[i] if i < len(row) else "" for row in raw_rows])
        for i in range(width)
    ]
    typed = [
        {col: convert(row[i] if i < len(row) else "", kinds[i])
         for i, col in enumerate(columns)}
        for row in raw_rows
    ]
    return Table(columns=columns, rows=typed)


class SQLErrorIO(Exception):
    pass
