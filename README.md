# csvq

**Query CSV files with a SQL subset — a hand-written SQL engine in pure Python, zero dependencies.**

[![CI](https://github.com/efealtiparmakoglu/csvq/actions/workflows/ci.yml/badge.svg)](https://github.com/efealtiparmakoglu/csvq/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org)

```
$ csvq "SELECT city, COUNT(*) AS n FROM people.csv AS p JOIN cities.csv AS c \
        ON p.city_id = c.id GROUP BY city ORDER BY n DESC LIMIT 3"
city    | n
--------+---
ankara  | 2
izmir   | 1
```

`csvq` is a complete little query engine: a tokenizer, a recursive-descent
SQL parser and an evaluator written from scratch on the standard library.
It infers column types from the data, joins files, aggregates, and prints
results as an aligned table, CSV, TSV, JSON or Markdown.

## Why csvq

- **Real SQL subset, hand-written.** Tokenizer + recursive-descent parser +
  evaluator — no regex hacks, no SQL library underneath. The grammar covers
  the queries people actually run on CSVs.
- **Type inference.** Columns are detected as int / float / bool / text per
  file; `age > 18` compares numbers, not strings. Empty cells become NULL
  in typed columns.
- **JOIN with qualified names.** `FROM a.csv AS a JOIN b.csv AS b ON a.id = b.id`,
  with smart `*` expansion: unambiguous columns stay unqualified, colliding
  ones are emitted as `table.col`.
- **Aggregates and grouping.** `COUNT(*)`, `COUNT(col)`, `SUM`, `AVG`, `MIN`,
  `MAX` with `GROUP BY` and `HAVING`.
- **Five output formats** for the next tool in the pipe: table, csv, tsv,
  json, markdown — plus exit codes a script can trust (0 ok, 1 runtime,
  2 syntax).
- **Zero dependencies.** Python 3.9+ standard library only.

## Install

```sh
pip install .          # from a clone; provides the `csvq` command
```

Or run directly: `python3 -m csvq.cli "..."`.

## Usage

```sh
csvq "SELECT * FROM data.csv"
csvq "SELECT name, age FROM people.csv WHERE age >= 18 ORDER BY age DESC LIMIT 10"
csvq "SELECT d.name, SUM(s.amount) AS total FROM sales.csv AS s \
      JOIN depts.csv AS d ON s.dept_id = d.id GROUP BY d.name HAVING SUM(s.amount) > 1000"
csvq "SELECT * FROM data.csv WHERE name LIKE 'a%'" -f json
csvq --no-header -d ';' "SELECT col1, col2 FROM export.csv"
```

| Option | Meaning |
|---|---|
| `-f, --format` | `table`, `csv`, `tsv`, `json`, `markdown` (default: table) |
| `-d, --delimiter` | input field delimiter (default `,`) |
| `--no-header` | files have no header row (columns named `col1..`) |

## The SQL subset

```sql
SELECT [DISTINCT] * | expr [AS alias], ...
FROM file.csv [AS alias]
[JOIN file2.csv [AS alias2] ON left = right]
[WHERE expr]
[GROUP BY col, ...]
[HAVING expr]
[ORDER BY col [ASC|DESC], ...]
[LIMIT n [OFFSET m]]
```

Expressions: comparisons (`= != < > <= >= LIKE` with `%`/`_` wildcards),
`AND`/`OR`/`NOT`, `IS [NOT] NULL`, literals (numbers, `'strings'`, TRUE,
FALSE, NULL), qualified columns (`table.col`). Aggregates: `COUNT(*)`,
`COUNT(col)`, `SUM`, `AVG`, `MIN`, `MAX`. Comments start with `--`.

Table names are file paths; an existing path is used as-is and a missing
alias defaults to the file stem. `LIKE` patterns use `%` (any run) and
`_` (one char), case-insensitively.

## Development

```sh
python3 -m unittest discover -s tests
```

22 tests cover the tokenizer (strings, numbers, paths, comments), the
parser (joins, aggregates, aliases, error positions), type inference and
conversion, engine semantics (joins, grouping, ordering, distinct,
limits), output formats including CSV quoting and JSON typing, and error
paths.

## License

MIT — see [LICENSE](LICENSE).
