"""Tokenizer: turns the SQL text into a stream of tokens.

Token kinds: NAME, NUMBER, STRING, OP, PUNCT, EOF. Keywords are recognized
case-insensitively at parse time from NAME tokens.
"""

from dataclasses import dataclass

KEYWORDS = {
    "SELECT", "DISTINCT", "FROM", "AS", "JOIN", "ON", "WHERE", "GROUP", "BY",
    "HAVING", "ORDER", "LIMIT", "OFFSET", "AND", "OR", "NOT", "LIKE", "NULL",
    "TRUE", "FALSE", "COUNT", "SUM", "AVG", "MIN", "MAX", "ASC", "DESC",
}


@dataclass
class Token:
    kind: str  # NAME, NUMBER, STRING, OP, PUNCT, EOF
    value: str
    pos: int

    def is_keyword(self, *names: str) -> bool:
        return self.kind == "NAME" and self.value.upper() in names


class SQLError(Exception):
    """Raised for tokenizer or parser errors; message includes position."""

    def __init__(self, message: str, pos: int = -1):
        if pos >= 0:
            message = f"{message} (at position {pos})"
        super().__init__(message)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "-" and text[i + 1: i + 2] == "-":  # comment to end of line
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "-" and text[i + 1: i + 2].isdigit():
            # negative number literal
            j = i + 1
            seen_dot = False
            while j < n and (text[j].isdigit() or (text[j] == "." and not seen_dot)):
                if text[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(Token("NUMBER", text[i:j], i))
            i = j
            continue
        if ch == "-":
            tokens.append(Token("OP", "-", i))
            i += 1
            continue
        if ch == "'":
            # string literal; '' escapes a quote
            j = i + 1
            parts = []
            while True:
                if j >= n:
                    raise SQLError("unterminated string literal", i)
                if text[j] == "'":
                    if text[j + 1: j + 2] == "'":
                        parts.append("'")
                        j += 2
                        continue
                    break
                parts.append(text[j])
                j += 1
            tokens.append(Token("STRING", "".join(parts), i))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and text[i + 1: i + 2].isdigit()):
            j = i
            seen_dot = False
            while j < n and (text[j].isdigit() or (text[j] == "." and not seen_dot)):
                if text[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(Token("NUMBER", text[i:j], i))
            i = j
            continue
        if ch.isalpha() or ch in "_./~":
            # NAME tokens include file paths (/tmp/x.csv, ./rel.csv, ~/x.csv)
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_./~-"):
                j += 1
            # qualified names like table.col stay one NAME token
            tokens.append(Token("NAME", text[i:j], i))
            i = j
            continue
        two = text[i: i + 2]
        if two in ("<=", ">=", "!=", "<>", "=="):
            tokens.append(Token("OP", "!=" if two == "!=" else ("=" if two == "==" else two), i))
            i += 2
            continue
        if ch in "=<>":
            tokens.append(Token("OP", ch, i))
            i += 1
            continue
        if ch in "(),*":
            tokens.append(Token("PUNCT", ch, i))
            i += 1
            continue
        raise SQLError(f"unexpected character {ch!r}", i)
    tokens.append(Token("EOF", "", n))
    return tokens
