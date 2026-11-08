"""Query engine: evaluates a Select AST over loaded tables."""
from __future__ import annotations

import re
from pathlib import Path

from .infer import Table, load_table
from .parser import (
    BinOp,
    Column,
    Func,
    Literal,
    Select,
    UnaryOp,
    parse,
)


class QueryError(Exception):
    pass


class Row:
    """One joined row; values are keyed by "col" and "table.col"."""

    __slots__ = ("values",)

    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get(self, col: Column) -> object:
        key = f"{col.table}.{col.name}" if col.table else col.name
        if key in self.values:
            return self.values[key]
        if col.table:
            raise QueryError(f"unknown table {col.table!r}")
        raise QueryError(f"unknown column {col.name!r}")


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value != ""
    return bool(value)


def _compare(op: str, left, right) -> bool:
    if op == "=":
        return _eq(left, right)
    if op == "!=":
        return not _eq(left, right)
    if left is None or right is None:
        return False
    try:
        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        if op == ">=":
            return left >= right
    except TypeError:
        # cross-type comparisons fall back to string comparison
        ls, rs = str(left), str(right)
        return {"<": ls < rs, ">": ls > rs, "<=": ls <= rs, ">=": ls >= rs}[op]
    raise QueryError(f"unknown operator {op!r}")


def _eq(left, right) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    return str(left) == str(right)


def like(value: object, pattern: object) -> bool:
    if value is None or pattern is None:
        return False
    regex = "^" + re.escape(str(pattern)).replace(r"\?", ".").replace(r"%", ".*") + "$"
    return re.match(regex, str(value), re.IGNORECASE) is not None


def eval_expr(expr, row: Row):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Column):
        return row.get(expr)
    if isinstance(expr, UnaryOp):
        value = eval_expr(expr.operand, row)
        if expr.op == "NOT":
            return not _truthy(value)
        if expr.op == "-":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise QueryError("cannot negate a non-number")
            return -value
        raise QueryError(f"unknown unary op {expr.op!r}")
    if isinstance(expr, BinOp):
        if expr.op == "AND":
            return _truthy(eval_expr(expr.left, row)) and _truthy(eval_expr(expr.right, row))
        if expr.op == "OR":
            return _truthy(eval_expr(expr.left, row)) or _truthy(eval_expr(expr.right, row))
        if expr.op == "LIKE":
            return like(eval_expr(expr.left, row), eval_expr(expr.right, row))
        return _compare(expr.op, eval_expr(expr.left, row), eval_expr(expr.right, row))
    raise QueryError(f"cannot evaluate {type(expr).__name__} here")


def is_aggregate(expr) -> bool:
    if isinstance(expr, Func):
        return True
    if isinstance(expr, BinOp):
        return is_aggregate(expr.left) or is_aggregate(expr.right)
    if isinstance(expr, UnaryOp):
        return is_aggregate(expr.operand)
    return False


class Engine:
    def __init__(self, delimiter: str = ",", no_header: bool = False,
                 base_dir: Path | None = None) -> None:
        self.delimiter = delimiter
        self.no_header = no_header
        self.base_dir = base_dir or Path.cwd()
        self._tables: dict[str, Table] = {}
        self._table_order: list[tuple[str, list[str]]] = []

    def _table_path(self, ref_path: str) -> Path:
        path = Path(ref_path)
        return path if path.is_absolute() else self.base_dir / path

    def load(self, ref_path: str, alias: str | None) -> str:
        key = alias or Path(ref_path).stem
        if key in self._tables:
            raise QueryError(f"table name {key!r} used twice")
        table = load_table(
            str(self._table_path(ref_path)), self.delimiter, not self.no_header
        )
        self._tables[key] = table
        self._table_order.append((key, list(table.columns)))
        return key

    def run_text(self, text: str) -> tuple[list[str], list[dict]]:
        select = parse(text)
        return self.run(select)

    def run(self, select: Select) -> tuple[list[str], list[dict]]:
        rows = self._from_and_joins(select)
        if select.where is not None:
            rows = [r for r in rows if _truthy(eval_expr(select.where, r))]

        has_aggregates = any(is_aggregate(item.expr) for item in select.items) or (
            select.having is not None and is_aggregate(select.having)
        )
        if select.group_by or has_aggregates:
            out_cols, out_rows = self._grouped(select, rows)
        else:
            out_cols, out_rows = self._plain(select, rows)

        if select.order_by:
            out_rows = self._ordered(select.order_by, out_cols, out_rows)
        if select.distinct:
            seen = set()
            unique = []
            for row in out_rows:
                key = tuple(sorted(row.items()))
                if key not in seen:
                    seen.add(key)
                    unique.append(row)
            out_rows = unique
        if select.offset:
            out_rows = out_rows[select.offset:]
        if select.limit is not None:
            out_rows = out_rows[: select.limit]
        return out_cols, out_rows

    # ------------------------------------------------------------- FROM/JOIN

    def _from_and_joins(self, select: Select) -> list[Row]:
        main_key = self.load(select.table.path, select.table.alias)
        main = self._tables[main_key]
        rows = [
            Row({**{f"{main_key}.{c}": v for c, v in r.items()},
                 **{c: v for c, v in r.items()}})
            for r in main.rows
        ]
        used_aliases = {main_key}

        for join in select.joins:
            jkey = self.load(join.table.path, join.table.alias)
            if jkey in used_aliases:
                raise QueryError(f"table name {jkey!r} used twice")
            used_aliases.add(jkey)
            jtable = self._tables[jkey]

            new_rows: list[Row] = []
            for left in rows:
                for jrow in jtable.rows:
                    values = dict(left.values)
                    values.update({f"{jkey}.{c}": v for c, v in jrow.items()})
                    values.update(jrow)
                    candidate = Row(values)
                    if _eq(eval_expr(join.left, candidate), eval_expr(join.right, candidate)):
                        new_rows.append(candidate)
            rows = new_rows
        return rows

    # ------------------------------------------------------------- projection

    def _output_columns(self, select: Select, sample_rows: list[Row]) -> list[tuple[str, object]]:
        """Returns (output_name, expr) pairs; expands * against row keys."""
        out = []
        for item in select.items:
            if item.star:
                # expand in table declaration order; a column is emitted
                # unqualified when its name is unique across all joined
                # tables, otherwise qualified (table.col) to stay unambiguous
                from collections import Counter
                pairs = [(key, c) for key, cols in self._table_order for c in cols]
                counts = Counter(c for _, c in pairs)
                for key, c in pairs:
                    if counts[c] == 1:
                        out.append((c, Column(c)))
                    else:
                        out.append((f"{key}.{c}", Column(c, key)))
            elif item.alias:
                out.append((item.alias, item.expr))
            elif isinstance(item.expr, Column):
                out.append((item.expr.name, item.expr))
            elif isinstance(item.expr, Func):
                arg = item.expr.arg
                col = arg.name if isinstance(arg, Column) else "*"
                out.append((f"{item.expr.name.lower()}({col})", item.expr))
            elif isinstance(item.expr, Column):
                out.append((item.expr.name, item.expr))
            else:
                out.append((self._expr_name(item.expr), item.expr))
        return out

    @staticmethod
    def _expr_name(expr) -> str:
        if isinstance(expr, Literal):
            return str(expr.value)
        if isinstance(expr, Column):
            return expr.name
        if isinstance(expr, BinOp):
            return f"{Engine._expr_name(expr.left)} {expr.op} {Engine._expr_name(expr.right)}"
        return "expr"

    def _plain(self, select: Select, rows: list[Row]) -> tuple[list[str], list[dict]]:
        cols = self._output_columns(select, rows)
        out_rows = []
        for row in rows:
            out_rows.append(
                {name: self._plain_value(eval_expr(expr, row)) for name, expr in cols}
            )
        return [name for name, _ in cols], out_rows

    @staticmethod
    def _plain_value(value):
        return value

    def _grouped(self, select: Select, rows: list[Row]) -> tuple[list[str], list[dict]]:
        if not select.group_by:
            groups = {(): rows}
        else:
            groups: dict[tuple, list[Row]] = {}
            for row in rows:
                key = tuple(eval_expr(col, row) for col in select.group_by)
                groups.setdefault(key, []).append(row)

        # output columns: aggregates + group-by columns
        cols = []
        for item in select.items:
            if item.star:
                raise QueryError("SELECT * cannot be combined with GROUP BY/aggregates")
            name = item.alias or self._agg_name(item.expr, select.group_by)
            cols.append((name, item.expr))
            if select.having is not None and item.expr is select.having:
                pass
        if select.having is not None and not any(
            h is h_expr for h, h_expr in cols
            for h_expr in [select.having]
        ):
            pass
        # HAVING may reference aggregates not in the select list; it is
        # evaluated below with the same group context.

        out_rows = []
        for key, group_rows in groups.items():
            if select.having is not None and not _truthy(
                self._eval_group_expr(select.having, key, select.group_by, group_rows)
            ):
                continue
            row_out = {}
            for name, expr in cols:
                row_out[name] = self._eval_group_expr(expr, key, select.group_by, group_rows)
            out_rows.append(row_out)
        return [name for name, _ in cols], out_rows

    def _eval_group_expr(self, expr, key: tuple, group_by: list[Column], group_rows: list[Row]):
        if isinstance(expr, Func):
            return self._aggregate(expr, group_rows)
        if isinstance(expr, Column):
            for col, value in zip(group_by, key):
                if col.name == expr.name and (col.table or "") == (expr.table or ""):
                    return value
            if not group_by:
                return None
            # fall through to single-row evaluation (grouped column)
            if group_rows:
                return eval_expr(expr, group_rows[0])
            return None
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, BinOp):
            if expr.op == "AND":
                return _truthy(self._eval_group_expr(expr.left, key, group_by, group_rows)) and \
                    _truthy(self._eval_group_expr(expr.right, key, group_by, group_rows))
            if expr.op == "OR":
                return _truthy(self._eval_group_expr(expr.left, key, group_by, group_rows)) or \
                    _truthy(self._eval_group_expr(expr.right, key, group_by, group_rows))
            if expr.op == "LIKE":
                return like(
                    self._eval_group_expr(expr.left, key, group_by, group_rows),
                    self._eval_group_expr(expr.right, key, group_by, group_rows),
                )
            return _compare(
                expr.op,
                self._eval_group_expr(expr.left, key, group_by, group_rows),
                self._eval_group_expr(expr.right, key, group_by, group_rows),
            )
        if isinstance(expr, UnaryOp):
            value = self._eval_group_expr(expr.operand, key, group_by, group_rows)
            return (not _truthy(value)) if expr.op == "NOT" else -value
        raise QueryError("unsupported grouped expression")

    @staticmethod
    def _aggregate(func: Func, rows: list[Row]):
        name = func.name
        if name == "COUNT" and func.arg is None:
            return len(rows)
        values = []
        for row in rows:
            v = eval_expr(func.arg, row)
            if v is not None:
                values.append(v)
        if name == "COUNT":
            return len(values)
        if not values:
            return None
        if name == "SUM":
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                raise QueryError("SUM needs numeric values")
            return sum(values)
        if name == "AVG":
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                raise QueryError("AVG needs numeric values")
            return sum(values) / len(values)
        if name == "MIN":
            return min(values)
        if name == "MAX":
            return max(values)
        raise QueryError(f"unknown aggregate {name!r}")

    @staticmethod
    def _agg_name(expr, group_by) -> str:
        if isinstance(expr, Func):
            arg = expr.arg
            col = arg.name if isinstance(arg, Column) else "*"
            return f"{expr.name.lower()}({col})"
        if isinstance(expr, Column):
            return expr.name
        return "expr"

    # ---------------------------------------------------------------- ordering

    def _ordered(self, order_by, out_cols: list[str], rows: list[dict]):
        """Sorts projected rows. ORDER BY keys reference output column names
        (or expressions evaluated over the projected row)."""
        colset = set(out_cols)

        def sort_key(expr):
            if isinstance(expr, Column):
                if expr.name in colset:
                    return lambda row: _sort_value(row[expr.name])
                raise QueryError(f"ORDER BY column {expr.name!r} is not in the output")
            if isinstance(expr, Literal):
                name = str(expr.value)
                if name in colset:
                    return lambda row: _sort_value(row[name])
                raise QueryError(f"ORDER BY column {name!r} is not in the output")

            def fn(row):
                row_row = Row({c: row.get(c) for c in row})
                return _sort_value(eval_expr(expr, row_row))
            return fn

        for expr, ascending in reversed(order_by):
            rows.sort(key=sort_key(expr), reverse=not ascending)
        return rows


def _sort_value(value):
    if value is None:
        return (0, "", 0.0)
    if isinstance(value, bool):
        return (1, str(value), float(value))
    if isinstance(value, (int, float)):
        return (2, "", float(value))
    return (1, str(value), 0.0)


def run_query(text: str, delimiter: str = ",", base_dir: Path | None = None,
              no_header: bool = False) -> tuple[list[str], list[dict]]:
    select = parse(text)
    engine = Engine(delimiter=delimiter, no_header=no_header, base_dir=base_dir)
    return engine.run_text(text)
