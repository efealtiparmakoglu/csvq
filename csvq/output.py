"""Output formatters: table (aligned), csv, tsv, json, markdown."""

import csv
import io
import json


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def format_table(columns: list[str], rows: list[dict]) -> str:
    cells = [[_cell(row.get(c)) for c in columns] for row in rows]
    widths = [len(c) for c in columns]
    for row in cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(values, fill=" "):
        return " | ".join(v.ljust(widths[i], fill) for i, v in enumerate(values))

    sep = "+".join("-" * (w + 2) for w in widths)
    out = [line(columns), sep]
    out.extend(line(row) for row in cells)
    return "\n".join(out)


def format_csv(columns: list[str], rows: list[dict], delimiter: str = ",") -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return buf.getvalue().rstrip("\n")


def format_json(columns: list[str], rows: list[dict]) -> str:
    def typed(value):
        if isinstance(value, float) and value.is_integer():
            return value
        return value

    return json.dumps(
        [{c: typed(row.get(c)) for c in columns} for row in rows],
        ensure_ascii=False,
        indent=2,
    )


def format_markdown(columns: list[str], rows: list[dict]) -> str:
    cells = [[_cell(row.get(c)) for c in columns] for row in rows]
    widths = [len(c) for c in columns]
    for row in cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(values):
        return "| " + " | ".join(v.ljust(widths[i]) for i, v in enumerate(values)) + " |"

    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    out = [line(columns), sep]
    out.extend(line(row) for row in cells)
    return "\n".join(out)


def format_output(fmt: str, columns: list[str], rows: list[dict],
                  delimiter: str = ",") -> str:
    if fmt == "table":
        return format_table(columns, rows)
    if fmt in ("csv", "tsv"):
        return format_csv(columns, rows, delimiter="\t" if fmt == "tsv" else delimiter)
    if fmt == "json":
        return format_json(columns, rows)
    if fmt == "markdown" or fmt == "md":
        return format_markdown(columns, rows)
    raise ValueError(f"unknown output format {fmt!r}")
