"""Recursive-descent parser: tokens -> a Select statement AST.

Grammar (the supported SQL subset):

    SELECT [DISTINCT] items FROM table [AS alias]
        (JOIN table [AS alias] ON left = right)*
        [WHERE expr]
        [GROUP BY col (, col)*]
        [HAVING expr]
        [ORDER BY col [ASC|DESC] (, ...)*]
        [LIMIT n [OFFSET m]]

    item: * | agg | expr [AS alias]
    agg: COUNT ( * | expr ) | (SUM|AVG|MIN|MAX) ( expr )
"""

from dataclasses import dataclass, field

from .tokenize import SQLError, Token, tokenize


@dataclass
class Column:
    name: str
    table: str | None = None


@dataclass
class Func:
    name: str  # COUNT/SUM/AVG/MIN/MAX (uppercase)
    arg: "Expr | None"  # None = COUNT(*)


@dataclass
class BinOp:
    op: str  # AND OR = != < > <= >= LIKE
    left: "Expr"
    right: "Expr"


@dataclass
class UnaryOp:
    op: str  # NOT, -
    operand: "Expr"


@dataclass
class Literal:
    value: object  # int, float, str, bool, None


Expr = Column | Func | BinOp | UnaryOp | Literal


@dataclass
class TableRef:
    path: str  # file path as written
    alias: str | None = None


@dataclass
class Join:
    table: TableRef
    left: Column
    right: Column


@dataclass
class SelectItem:
    expr: Expr
    alias: str | None = None
    star: bool = False


@dataclass
class Select:
    items: list[SelectItem]
    table: TableRef
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Column] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[tuple[Expr, bool]] = field(default_factory=list)  # (expr, ascending)
    limit: int | None = None
    offset: int = 0
    distinct: bool = False


AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class Parser:
    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect_punct(self, ch: str) -> Token:
        tok = self.peek()
        if tok.kind == "PUNCT" and tok.value == ch:
            return self.advance()
        raise SQLError(f"expected {ch!r}", tok.pos)

    def expect_keyword(self, *names: str) -> Token:
        tok = self.peek()
        if tok.is_keyword(*names):
            return self.advance()
        raise SQLError(f"expected {' or '.join(names)}", tok.pos)

    def at_keyword(self, *names: str) -> bool:
        return self.peek().is_keyword(*names)

    def at_punct(self, ch: str) -> bool:
        tok = self.peek()
        return tok.kind == "PUNCT" and tok.value == ch

    def parse(self) -> Select:
        self.expect_keyword("SELECT")
        distinct = False
        if self.at_keyword("DISTINCT"):
            self.advance()
            distinct = True

        items = [self.parse_select_item()]
        while self.at_punct(","):
            self.advance()
            items.append(self.parse_select_item())

        self.expect_keyword("FROM")
        table = self.parse_table_ref()

        joins: list[Join] = []
        while self.at_keyword("JOIN"):
            self.advance()
            jtable = self.parse_table_ref()
            self.expect_keyword("ON")
            left = self.parse_column()
            self.expect_op("=")
            right = self.parse_column()
            joins.append(Join(table=jtable, left=left, right=right))

        where = None
        if self.at_keyword("WHERE"):
            self.advance()
            where = self.parse_expr()

        group_by: list[Column] = []
        if self.at_keyword("GROUP"):
            self.advance()
            self.expect_keyword("BY")
            group_by.append(self.parse_column())
            while self.at_punct(","):
                self.advance()
                group_by.append(self.parse_column())

        having = None
        if self.at_keyword("HAVING"):
            self.advance()
            having = self.parse_expr()

        order_by: list[tuple[Expr, bool]] = []
        if self.at_keyword("ORDER"):
            self.advance()
            self.expect_keyword("BY")
            while True:
                expr = self.parse_operand()
                ascending = True
                if self.at_keyword("DESC"):
                    self.advance()
                    ascending = False
                elif self.at_keyword("ASC"):
                    self.advance()
                order_by.append((expr, ascending))
                if self.at_punct(","):
                    self.advance()
                    continue
                break

        limit = None
        offset = 0
        if self.at_keyword("LIMIT"):
            self.advance()
            tok = self.peek()
            if tok.kind != "NUMBER":
                raise SQLError("LIMIT needs a number", tok.pos)
            limit = int(self.advance().value)
            if self.at_keyword("OFFSET"):
                self.advance()
                tok = self.peek()
                if tok.kind != "NUMBER":
                    raise SQLError("OFFSET needs a number", tok.pos)
                offset = int(self.advance().value)

        tok = self.peek()
        if tok.kind != "EOF":
            raise SQLError(f"unexpected {tok.value!r} after end of statement", tok.pos)

        return Select(
            items=items, table=table, joins=joins, where=where,
            group_by=group_by, having=having, order_by=order_by,
            limit=limit, offset=offset, distinct=distinct,
        )

    def expect_op(self, op: str) -> Token:
        tok = self.peek()
        if tok.kind == "OP" and tok.value == op:
            return self.advance()
        raise SQLError(f"expected {op!r}", tok.pos)

    def parse_select_item(self) -> SelectItem:
        if self.at_punct("*"):
            self.advance()
            return SelectItem(expr=Literal(None), star=True)
        start = self.i
        expr = self.parse_expr()
        # bare aggregate keyword without parens is an error; parse_expr
        # handles the func case already
        alias = None
        if self.at_keyword("AS"):
            self.advance()
            tok = self.peek()
            if tok.kind != "NAME":
                raise SQLError("expected alias name", tok.pos)
            alias = self.advance().value
        elif self.i > start:
            tok = self.peek()
            # implicit alias: a NAME directly following an expr (not a keyword)
            if tok.kind == "NAME" and tok.value.upper() not in (
                "FROM", "WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "HAVING", "AND", "OR", "AS",
            ):
                alias = self.advance().value
        return SelectItem(expr=expr, alias=alias)

    def parse_table_ref(self) -> TableRef:
        tok = self.peek()
        if tok.kind != "NAME":
            raise SQLError("expected table file name", tok.pos)
        path = tok.value
        self.advance()
        alias = None
        if self.at_keyword("AS"):
            self.advance()
            tok = self.peek()
            if tok.kind != "NAME":
                raise SQLError("expected table alias", tok.pos)
            alias = self.advance().value
        elif self.peek().kind == "NAME" and not self.peek().is_keyword(
            "JOIN", "WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "ON", "AS",
        ):
            alias = self.advance().value
        return TableRef(path=path, alias=alias)

    def parse_column(self) -> Column:
        tok = self.peek()
        if tok.kind != "NAME":
            raise SQLError("expected column name", tok.pos)
        self.advance()
        if "." in tok.value:
            table, name = tok.value.split(".", 1)
            return Column(name=name, table=table)
        return Column(name=tok.value)

    def parse_expr(self) -> Expr:
        return self.parse_or()

    def parse_or(self) -> Expr:
        left = self.parse_and()
        while self.at_keyword("OR"):
            self.advance()
            left = BinOp("OR", left, self.parse_and())
        return left

    def parse_and(self) -> Expr:
        left = self.parse_not()
        while self.at_keyword("AND"):
            self.advance()
            left = BinOp("AND", left, self.parse_not())
        return left

    def parse_not(self) -> Expr:
        if self.at_keyword("NOT"):
            self.advance()
            return UnaryOp("NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> Expr:
        left = self.parse_operand()
        tok = self.peek()
        if tok.kind == "OP":
            self.advance()
            right = self.parse_operand()
            return BinOp(tok.value, left, right)
        if tok.is_keyword("LIKE"):
            self.advance()
            right = self.parse_operand()
            return BinOp("LIKE", left, right)
        if tok.is_keyword("IS"):
            self.advance()
            negate = False
            if self.at_keyword("NOT"):
                self.advance()
                negate = True
            tok2 = self.peek()
            if not tok2.is_keyword("NULL"):
                raise SQLError("expected NULL after IS", tok2.pos)
            self.advance()
            expr = BinOp("=", left, Literal(None))
            return UnaryOp("NOT", expr) if negate else expr
        return left

    def parse_operand(self) -> Expr:
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.advance()
            if "." in tok.value:
                return Literal(float(tok.value))
            return Literal(int(tok.value))
        if tok.kind == "STRING":
            self.advance()
            return Literal(tok.value)
        if tok.is_keyword("NULL"):
            self.advance()
            return Literal(None)
        if tok.is_keyword("TRUE"):
            self.advance()
            return Literal(True)
        if tok.is_keyword("FALSE"):
            self.advance()
            return Literal(False)
        if tok.kind == "PUNCT" and tok.value == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect_punct(")")
            return expr
        if tok.kind == "OP" and tok.value == "-":
            self.advance()
            operand = self.parse_operand()
            if isinstance(operand, Literal) and isinstance(operand.value, (int, float)):
                return Literal(-operand.value)
            return UnaryOp("-", operand)
        if tok.kind == "NAME":
            upper = tok.value.upper()
            if upper in AGGREGATES:
                self.advance()
                self.expect_punct("(")
                if upper == "COUNT" and self.at_punct("*"):
                    self.advance()
                    self.expect_punct(")")
                    return Func("COUNT", None)
                arg = self.parse_expr()
                self.expect_punct(")")
                return Func(upper, arg)
            return self.parse_column()
        raise SQLError(f"unexpected {tok.value!r}", tok.pos)


def parse(text: str) -> Select:
    return Parser(text).parse()
