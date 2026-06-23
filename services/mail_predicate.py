"""2j - boolean smart-mailbox predicate language.

grammar (recursive descent, OR loosest, implicit AND between adjacent terms, NOT tightest):
    expr   := or
    or     := and (OR and)*
    and    := not (AND? not)*        # adjacency = AND
    not    := NOT not | atom
    atom   := '(' expr ')' | term
    term   := field:value | "quoted" | word

fields (all cache-answerable): from, to, subject, label, text, is:(unread|read|flagged|muted).
a bare word is a text match over from+subject. operators are case-insensitive. empty query matches all.
"""

import re

_TOKEN = re.compile(r'\(|\)|"[^"]*"|[^()\s]+')  # parens are delimiters even when glued to a term


def _tokenize(q):
    raw = _TOKEN.findall(q or "")
    out = []
    for t in raw:
        low = t.lower()
        if t in ("(", ")"):
            out.append((t, t))
        elif low in ("and", "or", "not"):
            out.append((low.upper(), t))
        else:
            out.append(("TERM", t))
    return out


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def _eat(self):
        tok = self._peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.toks:
            return ("all",)
        node = self._or()
        return node

    def _or(self):
        node = self._and()
        while self._peek()[0] == "OR":
            self._eat()
            node = ("or", node, self._and())
        return node

    def _and(self):
        node = self._not()
        while True:
            kind = self._peek()[0]
            if kind == "AND":
                self._eat()
                node = ("and", node, self._not())
            elif kind in ("TERM", "NOT", "("):  # adjacency = implicit AND
                node = ("and", node, self._not())
            else:
                break
        return node

    def _not(self):
        if self._peek()[0] == "NOT":
            self._eat()
            return ("not", self._not())
        return self._atom()

    def _atom(self):
        kind, val = self._peek()
        if kind == "(":
            self._eat()
            node = self._or()
            if self._peek()[0] == ")":
                self._eat()
            return node
        if kind == "TERM":
            self._eat()
            return _term(val)
        # nothing usable - consume to avoid an infinite loop
        self._eat()
        return ("all",)


def _term(tok):
    if ":" in tok and not tok.startswith('"'):
        field, _, value = tok.partition(":")
        value = value.strip('"').lower()
        return ("term", field.lower(), value)
    return ("term", "text", tok.strip('"').lower())


def parse(query):
    return _Parser(_tokenize(query)).parse()


def _labels(msg):
    lab = msg.get("labels", [])
    if isinstance(lab, str):
        lab = lab.split(",")
    return {str(x).strip().lower() for x in lab if str(x).strip()}


def _term_matches(field, value, msg):
    sender = (msg.get("from") or msg.get("sender") or "").lower()
    subject = (msg.get("subject") or "").lower()
    if field == "from":
        return value in sender
    if field == "to":
        return value in (msg.get("to") or "").lower() or value in sender
    if field == "subject":
        return value in subject
    if field == "label":
        return value in _labels(msg)
    if field == "text":
        return value in sender or value in subject
    if field == "is":
        if value in ("unread", "unseen"):
            return not msg.get("seen")
        if value == "read":
            return bool(msg.get("seen"))
        if value in ("flagged", "starred"):
            return bool(msg.get("flagged"))
        if value == "muted":
            return bool(msg.get("muted"))
        return False
    return False  # unknown field never matches


def evaluate(node, msg):
    op = node[0]
    if op == "all":
        return True
    if op == "term":
        return _term_matches(node[1], node[2], msg)
    if op == "not":
        return not evaluate(node[1], msg)
    if op == "and":
        return evaluate(node[1], msg) and evaluate(node[2], msg)
    if op == "or":
        return evaluate(node[1], msg) or evaluate(node[2], msg)
    return False


def match_one(query, msg):
    return evaluate(parse(query), msg)


def match(query, msgs):
    ast = parse(query)
    return [m for m in msgs if evaluate(ast, m)]
