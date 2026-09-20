import json
import unittest

from csvq.engine import Engine, QueryError, run_query
from csvq.infer import infer_type, load_table
from csvq.parser import parse
from csvq.tokenize import SQLError, tokenize


def make_csv(path: str, rows: list[list[str]]) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(",".join(r) for r in rows) + "\n")
    return path


class TestInfer(unittest.TestCase):
    def test_infer_types(self):
        self.assertEqual(infer_type(["1", "2", "-30"]), int)
        self.assertEqual(infer_type(["1", "2.5"]), float)
        self.assertEqual(infer_type(["true", "FALSE"]), bool)
        self.assertEqual(infer_type(["a", "1"]), None)  # mixed -> text
        self.assertEqual(infer_type(["", ""]), None)

    def test_load_converts(self):
        path = make_csv("/tmp/csvq-t1.csv", [["name", "age", "score"],
                                             ["ali", "30", "9.5"],
                                             ["", "18", "8"]])
        table = load_table(path)
        self.assertEqual(table.columns, ["name", "age", "score"])
        self.assertEqual(table.rows[0], {"name": "ali", "age": 30, "score": 9.5})
        self.assertEqual(table.rows[1], {"name": "", "age": 18, "score": 8.0})


class TestTokenize(unittest.TestCase):
    def test_tokens(self):
        toks = tokenize("SELECT a FROM 'f.csv' WHERE b >= 1.5 AND c LIKE '%x'")
        kinds = [(t.kind, t.value) for t in toks]
        assert ("NAME", "SELECT") in kinds
        assert ("STRING", "f.csv") in kinds
        assert ("OP", ">=") in kinds

    def test_unterminated_string(self):
        with self.assertRaises(SQLError):
            tokenize("SELECT 'oops")


class TestParser(unittest.TestCase):
    def test_simple(self):
        sel = parse("SELECT a, b AS bb FROM t.csv WHERE a > 1 ORDER BY a DESC LIMIT 5 OFFSET 2")
        self.assertEqual([i.expr.name for i in sel.items], ["a", "b"])
        self.assertEqual(sel.items[1].alias, "bb")
        self.assertEqual(sel.table.path, "t.csv")
        self.assertEqual(sel.limit, 5)
        self.assertEqual(sel.offset, 2)
        self.assertFalse(sel.order_by[0][1])

    def test_join_and_aggregate(self):
        sel = parse(
            "SELECT d.dept, COUNT(*) AS n, AVG(p.price) FROM p.csv "
            "JOIN d.csv ON p.dept_id = d.id GROUP BY d.dept HAVING COUNT(*) > 2"
        )
        self.assertEqual(len(sel.joins), 1)
        self.assertEqual(len(sel.group_by), 1)
        self.assertIsNotNone(sel.having)
        self.assertEqual(sel.items[1].expr.name, "COUNT")

    def test_errors(self):
        with self.assertRaises(SQLError):
            parse("UPDATE t.csv")
        with self.assertRaises(SQLError):
            parse("SELECT a FROM t.csv ORDER BY")
        with self.assertRaises(SQLError):
            parse("SELECT FROM t.csv")


class TestEngine(unittest.TestCase):
    def setUp(self):
        make_csv("/tmp/csvq-people.csv", [
            ["name", "age", "city_id", "active"],
            ["ali", "30", "1", "true"],
            ["ayse", "25", "2", "false"],
            ["mehmet", "41", "1", "true"],
            ["zeynep", "17", "3", ""],
        ])
        make_csv("/tmp/csvq-cities.csv", [
            ["id", "city"],
            ["1", "ankara"],
            ["2", "izmir"],
            ["3", "antalya"],
        ])

    def q(self, text):
        return run_query(text)

    def test_select_all(self):
        cols, rows = self.q("SELECT * FROM /tmp/csvq-people.csv")
        self.assertEqual(cols, ["name", "age", "city_id", "active"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["age"], 30)

    def test_where_and_projection(self):
        cols, rows = self.q(
            "SELECT name, age FROM /tmp/csvq-people.csv WHERE age >= 25 AND active = true ORDER BY age"
        )
        self.assertEqual([r["name"] for r in rows], ["ali", "mehmet"])
        self.assertEqual(rows[1]["age"], 41)

    def test_like(self):
        cols, rows = self.q("SELECT name FROM /tmp/csvq-people.csv WHERE name LIKE 'a%'")
        self.assertEqual(sorted(r["name"] for r in rows), ["ali", "ayse"])

    def test_not_like_and_null(self):
        cols, rows = self.q(
            "SELECT name FROM /tmp/csvq-people.csv WHERE active IS NULL"
        )
        self.assertEqual([r["name"] for r in rows], ["zeynep"])

    def test_join(self):
        cols, rows = self.q(
            "SELECT name, city FROM /tmp/csvq-people.csv "
            "JOIN /tmp/csvq-cities.csv ON city_id = id ORDER BY name"
        )
        self.assertEqual([r["name"] for r in rows], ["ali", "ayse", "mehmet", "zeynep"])
        self.assertEqual(rows[0]["city"], "ankara")
        self.assertEqual(rows[1]["city"], "izmir")

    def test_join_qualified(self):
        cols, rows = self.q(
            "SELECT people.name, cities.city FROM /tmp/csvq-people.csv AS people "
            "JOIN /tmp/csvq-cities.csv AS cities ON people.city_id = cities.id WHERE city = 'izmir'"
        )
        self.assertEqual(rows[0]["name"], "ayse")

    def test_group_aggregates(self):
        cols, rows = self.q(
            "SELECT city_id, COUNT(*) AS n, AVG(age) AS avg_age FROM /tmp/csvq-people.csv GROUP BY city_id ORDER BY city_id"
        )
        self.assertEqual(len(rows), 3)
        by_city = {r["city_id"]: r for r in rows}
        self.assertEqual(by_city[1]["n"], 2)
        self.assertEqual(by_city[1]["avg_age"], 35.5)
        self.assertEqual(by_city[3]["n"], 1)

    def test_count_star_total(self):
        cols, rows = self.q("SELECT COUNT(*) AS total FROM /tmp/csvq-people.csv")
        self.assertEqual(rows[0]["total"], 4)

    def test_distinct_limit(self):
        cols, rows = self.q(
            "SELECT DISTINCT city_id FROM /tmp/csvq-people.csv ORDER BY city_id LIMIT 2"
        )
        self.assertEqual([r["city_id"] for r in rows], [1, 2])

    def test_unknown_column_is_error(self):
        with self.assertRaises(QueryError):
            self.q("SELECT nope FROM /tmp/csvq-people.csv")

    def test_unknown_table_file(self):
        from csvq.infer import SQLErrorIO
        with self.assertRaises(SQLErrorIO):
            self.q("SELECT a FROM /tmp/csvq-does-not-exist-xyz.csv")

    def test_min_max_sum(self):
        cols, rows = self.q(
            "SELECT MIN(age) AS lo, MAX(age) AS hi, SUM(age) AS total FROM /tmp/csvq-people.csv"
        )
        self.assertEqual((rows[0]["lo"], rows[0]["hi"], rows[0]["total"]), (17, 41, 113))


class TestOutput(unittest.TestCase):
    def setUp(self):
        self.cols = ["a", "b"]
        self.rows = [{"a": 1, "b": "x,y"}, {"a": 2.5, "b": None}]

    def test_csv_quoting(self):
        from csvq.output import format_output
        out = format_output("csv", self.cols, self.rows)
        lines = out.splitlines()
        self.assertEqual(lines[0], "a,b")
        self.assertEqual(lines[1], '1,"x,y"')
        self.assertEqual(lines[2], "2.5,")

    def test_json(self):
        from csvq.output import format_output
        data = json.loads(format_output("json", self.cols, self.rows))
        self.assertEqual(data[0]["a"], 1)
        self.assertIsNone(data[1]["b"])

    def test_markdown(self):
        from csvq.output import format_output
        out = format_output("markdown", self.cols, self.rows)
        self.assertTrue(out.splitlines()[1].startswith("|"))


if __name__ == "__main__":
    unittest.main()
