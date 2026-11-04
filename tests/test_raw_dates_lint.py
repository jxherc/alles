"""u.04, decision 0063: no raw iso date reaches visible text.

a `YYYY-MM-DD` value (a `.date`, `due_date`, `ymd(...)`, `toISOString().slice(0, 10)`,
`calendarDateKey(...)`) may be a data attribute, an input value, an api param or a sort key. it
may not be drawn: text content, html text, a title or aria-label, a `t(..., { date })` param.
those go through when.js (`whenDay`, `whenElement`, `whenHtml`, ...) or the locale formatters in
i18n.js (`formatDate`, `formatCalendarDate`, `formatDateTime`, ...).

the check reads the js in static/js, tokenizes it (comments, strings, regexes, nested template
literals), and looks at every place text is drawn:
  - an `${...}` inside an html template where it lands in text or in a title, aria-label,
    placeholder or alt attribute;
  - the right side of textContent, innerText, title, placeholder, alt, label, setAttribute of
    those, createTextNode, insertAdjacentText and the text argument of el()/_el()/node();
  - a property of a `{ ... }` params object passed to t(), tr(), trp(), tp();
  - a visible property of an object literal (label, text, sub, meta, detail, ...).
a value counts as a raw iso date when it reads `.date`, `due_date`, `.due`, `ymd(...)`,
`calendarDateKey(...)`, `.slice(0, 10)`, `.toISOString()` and the like, or a local that was set
from one of those, and the expression does not go through a formatter first.

ALLOWED names every real exception, keyed by file and the expression, with the reason. an entry
that no longer matches anything fails the test, so the list cannot rot.
"""

import functools
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

# files that are the formatters themselves
SKIP_FILES = {"static/js/when.js", "static/js/i18n.js"}

# helpers that turn an iso value into words. each was read: it formats through Intl / i18n.js
SAFE_CALL = re.compile(
    r"^(when\w*|format[A-Z]\w*|\w*[dD]ayLabel|\w*[dD]ateLabel|shortDate|readerDate|longDay|"
    r"fmtDate\w*|prettyDate|countdownText|relTime)$"
)
I18N_CALL = re.compile(r"^(t|tr|trp|tp|tl)$")
# a call chain that formats: `x.date.toLocaleDateString(...)`, `fmt.format(x.date)`
FORMAT_CHAIN = re.compile(r"[\w$.\[\]()]*\.(toLocale\w*String|format|formatToParts)\(")

SOURCE_NAMES = {
    "due_date",
    "dueDate",
    "dateKey",
    "date_key",
    "dstr",
    "isoDate",
    "isoDay",
    "dayKey",
    "todayKey",
}
SOURCE_MEMBERS = (
    "date|due|due_date|dueDate|date_key|dateKey|iso|dayKey|todayKey|birthday|when|mtime|modified"
)
SOURCE_CALLS = r"(?:ymd|_ymd|calendarDateKey|dayKey|todayKey|_today|today|isoDay|localDay|dateKey|isoDate|addDays|_addDays|_iso|iso|_todayISO|todayISO|localISO|_localISO)"
SOURCE_PATTERNS = [
    re.compile(r"\.toISOString\(\)"),
    re.compile(r"\.(?:slice|substring|substr)\(\s*0\s*,\s*10\s*\)"),
    re.compile(r"\.split\(\s*'T'\s*\)\s*\[\s*0\s*\]"),
    re.compile(r"(?<![\w$])" + SOURCE_CALLS + r"\("),
    re.compile(r"\.(?:" + SOURCE_MEMBERS + r")(?![\w$(])"),
    re.compile(r"\.(?:[a-z_]+_at|[a-z_]+_(?:date|end|start|on)|start_dt|end_dt|expires)(?![\w$(])"),
]
LOCAL_DECL = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*")

TEXT_PROPS = r"(?:textContent|innerText|title|placeholder|alt|label|ariaLabel)"
VISIBLE_ATTRS = {"title", "aria-label", "placeholder", "alt", "aria-valuetext", "aria-description"}
VISIBLE_KEYS = {
    "label", "text", "sub", "subtitle", "meta", "detail", "hint", "caption", "message",
    "line", "note", "heading", "summary", "description", "title",
}  # fmt: skip
EL_CALLS = {"el", "_el", "node"}

# (file, expression) -> why it may stay. "left: <owner>" is for files another session owns.
NUMBERS = (
    "left: s11b-numbers (health and money screens, being redrawn with the numbers-show-change pass)"
)
SETTINGS = "left: s8 (settings and server panels)"
ALLOWED = {
    ("static/js/money.js", "esc(c.target.date)"): NUMBERS,
    ("static/js/money.js", "esc(target.date)"): NUMBERS,
    ("static/js/money.js", "txn.date || t('money.undated')"): NUMBERS,
    ("static/js/journal.js", "esc(e.date.slice(0, 4))"): "the year of an entry, not a date",
    ("static/js/server_workbench.js", "String(when)"): SETTINGS,
    (
        "static/js/server_workbench.js",
        "`${domains} · ${item.expires_on || t('server.wb_no_expiry')}`",
    ): SETTINGS,
    (
        "static/js/settings/connections.js",
        "_esc((r.updated_at || '').replace('T', ' ').slice(0, 19))",
    ): SETTINGS,
}


class Scan:
    """one tokenized js file: masked code, plus every template literal with its parts."""

    def __init__(self, source):
        self.src = source
        self.n = len(source)
        self.masked = list(source)
        self.templates = []
        self._code(0, False)
        self.code = "".join(self.masked)

    def _mask(self, a, b):
        for k in range(a, b):
            if self.src[k] != "\n":
                self.masked[k] = " " if self.masked[k] != "_" else "_"

    def _blank(self, a, b, ch="_"):
        for k in range(a, b):
            if self.src[k] != "\n":
                self.masked[k] = ch

    def _regex_allowed(self, pos):
        k = pos - 1
        while k >= 0 and self.src[k] in " \t\r\n":
            k -= 1
        if k < 0:
            return True
        c = self.src[k]
        if c in "(,=:[!&|?{};+-*%<>~^":
            return True
        word = re.search(r"[A-Za-z_$][\w$]*$", self.src[max(0, k - 12) : k + 1])
        return bool(
            word
            and word.group(0)
            in {
                "return",
                "typeof",
                "case",
                "in",
                "of",
                "void",
                "yield",
                "await",
                "delete",
                "throw",
                "else",
            }
        )

    def _code(self, pos, stop_at_brace):
        depth = 0
        src, n = self.src, self.n
        while pos < n:
            c = src[pos]
            two = src[pos : pos + 2]
            if two == "//":
                end = src.find("\n", pos)
                end = n if end < 0 else end
                self._mask(pos, end)
                pos = end
                continue
            if two == "/*":
                end = src.find("*/", pos + 2)
                end = n if end < 0 else end + 2
                self._mask(pos, end)
                pos = end
                continue
            if c in "'\"":
                end = pos + 1
                while end < n and src[end] != c and src[end] != "\n":
                    end += 2 if src[end] == "\\" else 1
                self._blank(pos + 1, end)
                pos = end + 1
                continue
            if c == "`":
                pos = self._template(pos)
                continue
            if c == "/" and self._regex_allowed(pos):
                end, in_class = pos + 1, False
                while end < n and src[end] != "\n":
                    if src[end] == "\\":
                        end += 2
                        continue
                    if src[end] == "[":
                        in_class = True
                    elif src[end] == "]":
                        in_class = False
                    elif src[end] == "/" and not in_class:
                        break
                    end += 1
                self._blank(pos + 1, end)
                pos = end + 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                if stop_at_brace and depth == 0:
                    return pos
                depth -= 1
            pos += 1
        return pos

    def _template(self, pos):
        src, n = self.src, self.n
        tpl = {"start": pos, "static": [], "exprs": []}
        pos += 1
        static_start = pos
        while pos < n:
            c = src[pos]
            if c == "\\":
                self._blank(pos, min(pos + 2, n))
                pos += 2
            elif c == "`":
                tpl["static"].append((static_start, pos))
                tpl["end"] = pos + 1
                self.templates.append(tpl)
                return pos + 1
            elif c == "$" and src[pos + 1 : pos + 2] == "{":
                tpl["static"].append((static_start, pos))
                self._blank(static_start, pos)
                begin = pos + 2
                end = self._code(begin, True)
                tpl["exprs"].append((begin, end))
                pos = end + 1
                static_start = pos
            else:
                if c != "\n":
                    self.masked[pos] = "_"
                pos += 1
        return pos

    def view(self, a, b, mode):
        """the masked code from a to b, with the templates inside it blanked: every one for the
        template check itself, only the html ones for a text sink (a plain template is the text)."""
        chars = list(self.code[a:b])
        for tpl in self.templates:
            if a <= tpl["start"] and tpl["end"] <= b:
                if mode == "all" or any("<" in self.src[x:y] for x, y in tpl["static"]):
                    for k in range(tpl["start"], tpl["end"]):
                        if self.src[k] != "\n":
                            chars[k - a] = " "
        return "".join(chars)

    def line(self, pos):
        return self.src.count("\n", 0, pos) + 1


def balanced(code, open_at):
    """index just past the bracket that closes the one at open_at."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[code[open_at]]]
    k = open_at + 1
    while k < len(code) and stack:
        ch = code[k]
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch == stack[-1]:
            stack.pop()
        k += 1
    return k


def drop_calls(code, name_ok):
    """remove every call whose name passes name_ok, argument list included."""
    out, pos = [], 0
    for m in re.finditer(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", code):
        if m.start() < pos or not name_ok(m.group(1)):
            continue
        out.append(code[pos : m.start()])
        pos = balanced(code, m.end() - 1)
    out.append(code[pos:])
    return " ".join(out)


def drop_member_calls(code, name_ok):
    out, pos = [], 0
    for m in re.finditer(r"\.\s*([A-Za-z_$][\w$]*)\s*\(", code):
        if m.start() < pos or not name_ok(m.group(1)):
            continue
        out.append(code[pos : m.start()])
        pos = balanced(code, m.end() - 1)
    out.append(code[pos:])
    return " ".join(out)


def drop_formatter_chains(code):
    """`x.date.toLocaleDateString(...)` and `fmt.format(x.date)` carry no raw date."""
    while True:
        m = FORMAT_CHAIN.search(code)
        if not m:
            return code
        end = balanced(code, m.end() - 1)
        code = code[: m.start()] + " " + code[end:]


TRANSPARENT = {"esc", "_esc", "escapeHtml", "escHtml", "String", "lowerCase"}
OPERATORS = (("&&", "A"), ("||", "O"), ("??", "N"))


def split_top(code):
    """the value segments of an expression at its top level: [(text, operator that follows)]."""
    segs, stack, start, k = [], [], 0, 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    open_q = 0
    while k < len(code):
        ch = code[k]
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        elif not stack:
            two = code[k : k + 2]
            if two in ("&&", "||", "??"):
                segs.append((code[start:k], {"&&": "A", "||": "O", "??": "N"}[two]))
                k += 2
                start = k
                continue
            if ch == "?" and code[k + 1 : k + 2] != "." and code[k - 1 : k] != "?":
                segs.append((code[start:k], "Q"))
                open_q += 1
                start = k + 1
            elif ch == ":" and open_q:
                segs.append((code[start:k], "C"))
                open_q -= 1
                start = k + 1
        k += 1
    segs.append((code[start:], ""))
    return segs


def blank_groups(text):
    out, stack = [], []
    pairs = {"(": ")", "[": "]", "{": "}"}
    for ch in text:
        if stack:
            if ch in pairs:
                stack.append(pairs[ch])
            elif ch == stack[-1]:
                stack.pop()
                if not stack:
                    out.append(ch)
                continue
            out.append(" ")
        else:
            out.append(ch)
            if ch in pairs:
                stack.append(pairs[ch])
    return "".join(out)


def recurse_groups(text):
    out, k = [], 0
    while k < len(text):
        if text[k] == "$" and text[k + 1 : k + 2] == "{":
            end = balanced(text, k + 1)
            out.append("${" + strip_conditions(text[k + 2 : end - 1]) + "}")
            k = end
        elif text[k] == "(":
            end = balanced(text, k)
            out.append("(" + strip_conditions(text[k + 1 : end - 1]) + ")")
            k = end
        else:
            out.append(text[k])
            k += 1
    return "".join(out)


def strip_conditions(code):
    """keep only what an expression can draw: not the test of a ternary, the left of &&, a
    comparison or a negation."""
    kept = []
    for text, op in split_top(code):
        flat = blank_groups(text)
        if (
            op in ("Q", "A")
            or re.search(r"===|!==|[^=!<>]==[^=]|!=[^=]", " " + flat + " ")
            or flat.lstrip().startswith("!")
        ):
            continue
        kept.append(recurse_groups(text))
    return " ".join(kept)


def drop_arrow_heads(code):
    """an arrow's parameters are not values, and a block body is statements whose templates are
    checked on their own."""
    while True:
        m = re.search(r"(?:\([^()]*\)|[\w$]+)\s*=>\s*", code)
        if not m:
            return code
        tail = m.end()
        if code[tail : tail + 1] == "{":
            end = balanced(code, tail)
            code = code[: m.start()] + " " + code[end:]
        else:
            code = code[: m.start()] + " " + code[tail:]


def tainted(code, locals_):
    """does this masked expression put a raw iso date into text?"""
    code = drop_arrow_heads(code)
    code = drop_formatter_chains(code)
    code = drop_calls(code, lambda name: bool(SAFE_CALL.match(name) or I18N_CALL.match(name)))
    code = drop_member_calls(code, lambda name: bool(SAFE_CALL.match(name)))
    code = strip_conditions(code)
    code = drop_calls(
        code, lambda name: name not in TRANSPARENT and not re.fullmatch(SOURCE_CALLS, name)
    )
    code = code.replace("`", " ")
    for pattern in SOURCE_PATTERNS:
        if pattern.search(code):
            return True
    for name in SOURCE_NAMES | locals_:
        for m in re.finditer(r"(?<![\w$.])" + re.escape(name) + r"(?![\w$(:])(?!\s*=[^=>])", code):
            member = re.match(r"\s*(?:\??\.([\w$]+)(\()?|\[)", code[m.end() :])
            if member and not member.group(2) and name in locals_:
                continue  # `info.mood`: a property of the local, not the local
            return True
    return False


def tail_expr(code, pos):
    """the expression that starts at pos, up to the end of the statement or argument."""
    k, stack = pos, []
    pairs = {"(": ")", "[": "]", "{": "}"}
    while k < len(code):
        ch = code[k]
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        elif not stack and ch in ";)]}":
            break
        elif not stack and ch == ",":
            break
        elif not stack and ch == "\n":
            rest = code[k:].lstrip()
            head = code[pos:k].rstrip()
            if not (
                rest[:1] in {"+", "?", ":", ".", "|", "&"}
                or head[-1:] in {"+", "?", ":", "|", "&", "=", "(", ","}
            ):
                break
        k += 1
    return code[pos:k]


def split_args(code):
    parts, stack, start = [], [], 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    for k, ch in enumerate(code):
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        elif not stack and ch == ",":
            parts.append((start, k))
            start = k + 1
    parts.append((start, len(code)))
    return parts


def html_state(static_before):
    """where does an interpolation land, given the template text before it: 'text', an attribute
    name, or None when the template is not html."""
    if "<" not in static_before:
        m = re.search(r"([\w:-]+)=\"[^\"]*$", static_before)
        return m.group(1) if m else None
    in_tag, quote, attr = False, "", ""
    k = 0
    while k < len(static_before):
        ch = static_before[k]
        if not in_tag:
            if ch == "<" and re.match(r"</?[A-Za-z]", static_before[k:]):
                in_tag, quote, attr = True, "", ""
        elif quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            m = re.search(r"([\w:-]+)\s*=\s*$", static_before[:k])
            attr = m.group(1) if m else ""
        elif ch == ">":
            in_tag = False
        k += 1
    if not in_tag:
        return "text"
    return attr if quote else ""


def near(decl, pos):
    return {name for name, spots in decl.items() if any(0 <= pos - spot <= 3000 for spot in spots)}


def finds(path):
    """every raw iso date drawn in this file: [(line, kind, expression)]."""
    source = path.read_text(encoding="utf-8")
    scan = Scan(source)
    code, src = scan.code, scan.src
    out = {}

    def norm(a, b):
        return " ".join(src[a:b].split())

    def add(pos, kind, a, b):
        out.setdefault((norm(a, b)), (scan.line(pos), kind))

    # locals set from a raw date carry it along, for the next 3000 characters (one function)
    decl = {}
    for _ in range(2):
        for m in LOCAL_DECL.finditer(code):
            name = m.group(1)
            if len(name) < 3 or name in SOURCE_NAMES or m.start() in decl.get(name, ()):
                continue
            init = tail_expr(code, m.end())
            if (
                len(init) < 160
                and not re.search(r"=>|\.(map|filter|join|reduce)\(|await\b|^\s*\{|<", init)
                and tainted(init, near(decl, m.start()))
            ):
                decl.setdefault(name, []).append(m.start())

    # 1. html templates
    for tpl in scan.templates:
        static = [src[a:b] for a, b in tpl["static"]]
        for i, (a, b) in enumerate(tpl["exprs"]):
            state = html_state("_".join(static[: i + 1]))
            if state is None or not (state == "text" or state in VISIBLE_ATTRS):
                continue
            if tainted(scan.view(a, b, "all"), near(decl, a)):
                add(a, "template " + state, a, b)

    # 2. text assignments
    for m in re.finditer(r"\.(?:" + TEXT_PROPS + r")\s*\+?=(?!=)\s*", code):
        a = m.end()
        b = a + len(tail_expr(code, a))
        if tainted(scan.view(a, b, "html"), near(decl, a)):
            add(m.start(), "assign " + m.group(0).split("=")[0].strip(" .+"), a, b)
    for m in re.finditer(r"setAttribute\(\s*(['\"])(_*)\1\s*,\s*", code):
        name = src[m.start(2) : m.end(2)]
        if name not in VISIBLE_ATTRS:
            continue
        a = m.end()
        b = a + len(tail_expr(code, a))
        if tainted(scan.view(a, b, "html"), near(decl, a)):
            add(m.start(), "setAttribute " + name, a, b)
    for m in re.finditer(r"(?:createTextNode|insertAdjacentText)\(", code):
        end = balanced(code, m.end() - 1)
        inner = scan.view(m.end(), end - 1, "html")
        if tainted(inner, near(decl, m.start())):
            add(m.start(), "text node", m.end(), end - 1)
    for m in re.finditer(r"(?<![\w$.])(el|_el|node|_row)\(", code):
        end = balanced(code, m.end() - 1)
        inner = scan.view(m.end(), end - 1, "html")
        for k, (a, b) in enumerate(split_args(inner)):
            if k >= 1 and tainted(inner[a:b], near(decl, m.start())):
                add(m.end() + a, "el text", m.end() + a, m.end() + b)

    # 3. params of an i18n call
    for m in re.finditer(r"(?<![\w$.])(t|tr|trp|tp|tl)\(", code):
        end = balanced(code, m.end() - 1)
        inner = scan.view(m.end(), end - 1, "html")
        for om in re.finditer(r"\{", inner):
            oend = balanced(inner, om.start())
            body = inner[om.start() + 1 : oend - 1]
            for a, b in split_args(body):
                piece = body[a:b]
                pm = re.match(r"\s*([A-Za-z_$][\w$]*)\s*(?::\s*(.*))?$", piece, re.S)
                if not pm:
                    continue
                value = pm.group(2) if pm.group(2) is not None else pm.group(1)
                vstart = (
                    m.end()
                    + om.start()
                    + 1
                    + a
                    + (pm.start(2) if pm.group(2) is not None else pm.start(1))
                )
                if tainted(value, near(decl, m.start())):
                    add(vstart, "t() param " + pm.group(1), vstart, vstart + len(value))
            break  # the first object is the params

    # 4. visible properties of object literals
    for m in re.finditer(
        r"(?<![\w$.?])(" + "|".join(sorted(VISIBLE_KEYS)) + r")\s*:\s*(?!:)", code
    ):
        a = m.end()
        b = a + len(tail_expr(code, a))
        if tainted(scan.view(a, b, "html"), near(decl, a)):
            add(m.start(), "property " + m.group(1), a, b)

    return [
        (line, kind, expr) for expr, (line, kind) in sorted(out.items(), key=lambda kv: kv[1][0])
    ]


@functools.lru_cache(maxsize=1)
def all_finds():
    result = {}
    for path in sorted(JS.rglob("*.js")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in SKIP_FILES:
            continue
        for line, kind, expr in finds(path):
            result[(rel, expr)] = (line, kind)
    return result


class RawDateTests(unittest.TestCase):
    def test_no_raw_iso_date_is_drawn(self):
        found = all_finds()
        loose = {key: where for key, where in found.items() if key not in ALLOWED}
        report = "\n".join(
            f"{file}:{line}  [{kind}]  {expr[:140]}"
            for (file, expr), (line, kind) in sorted(loose.items())
        )
        self.assertFalse(
            loose,
            "a raw YYYY-MM-DD reaches visible text. draw it with whenDay/whenElement/whenHtml "
            "(static/js/when.js) or a formatter from i18n.js, or name the exception in ALLOWED:\n"
            + report,
        )

    def test_every_exception_still_matches(self):
        found = all_finds()
        stale = sorted(key for key in ALLOWED if key not in found)
        self.assertFalse(
            stale,
            "ALLOWED entries that match nothing (remove them):\n" + "\n".join(map(str, stale)),
        )
        for key, why in ALLOWED.items():
            self.assertTrue(why.strip(), key)


class ScannerTests(unittest.TestCase):
    """the scanner itself, on small samples."""

    def run_on(self, code):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.js"
            path.write_text(code, encoding="utf-8")
            return [expr for _, _, expr in finds(path)]

    def test_flags_text_and_title(self):
        got = self.run_on(
            'el.textContent = task.due_date;\nrow.innerHTML = `<b title="${x.date}">${esc(x.date)}</b>`;'
        )
        self.assertEqual(got, ["task.due_date", "x.date", "esc(x.date)"])

    def test_flags_t_params_and_locals(self):
        got = self.run_on(
            "const stamp = e.date.slice(0, 10);\nlabel.textContent = t('k', { date: stamp });"
        )
        self.assertEqual(got, ["stamp"])

    def test_a_test_or_a_branch_is_not_drawn(self):
        got = self.run_on(
            "a.innerHTML = `${x.date ? whenHtml(x.date) : ''}${x.due && x.due < today ? t('late') : ''}`;\n"
            "b.textContent = x.date === today ? t('today') : whenDay(x.date);\n"
            "c.textContent = !x.date ? t('none') : '';\n"
        )
        self.assertEqual(got, [])

    def test_a_fallback_or_a_plain_template_is_drawn(self):
        got = self.run_on(
            "a.textContent = x.date || t('none');\nb.textContent = `${n} · ${x.due_date}`;"
        )
        self.assertEqual(got, ["x.date || t('none')", "`${n} · ${x.due_date}`"])

    def test_formatters_and_data_attributes_pass(self):
        got = self.run_on(
            "a.textContent = whenDay(x.date);\n"
            'b.innerHTML = `<i data-date="${x.date}" title="${esc(formatCalendarDate(x.date))}">${whenHtml(x.date)}</i>`;\n'
            "c.value = x.date;\n"
            "fetch(`/api/x?date=${x.date}`);\n"
            "d.textContent = x.date.toLocaleDateString('en');\n"
            "// el.textContent = x.date\n"
            "e.textContent = 'x.date';\n"
        )
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
