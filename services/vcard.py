"""minimal vCard 3.0 read/write — FN/N, EMAIL, TEL, NOTE. no deps, good enough
for round-tripping contacts in/out of phones and other address books."""


def _esc(s) -> str:
    return (
        str(s or "")
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append({"n": "\n", "N": "\n"}.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def to_vcard(contacts) -> str:
    lines = []
    for c in contacts:
        name = c.get("name", "")
        lines += ["BEGIN:VCARD", "VERSION:3.0", "FN:" + _esc(name)]
        if name:
            lines.append("N:" + _esc(name) + ";;;;")
        if c.get("email"):
            lines.append("EMAIL;TYPE=INTERNET:" + _esc(c["email"]))
        if c.get("phone"):
            lines.append("TEL:" + _esc(c["phone"]))
        if c.get("notes"):
            lines.append("NOTE:" + _esc(c["notes"]))
        lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def parse_vcards(text: str) -> list[dict]:
    cards, cur = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        up = line.upper()
        if up == "BEGIN:VCARD":
            cur = {"name": "", "email": "", "phone": "", "notes": ""}
        elif up == "END:VCARD":
            if cur and (cur["name"] or cur["email"]):
                cards.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            k = key.split(";")[0].upper()
            val = _unesc(val)
            if k == "FN":
                cur["name"] = val
            elif k == "N" and not cur["name"]:
                p = val.split(";")
                cur["name"] = (
                    " ".join(x for x in [(p[1] if len(p) > 1 else ""), p[0]] if x).strip() or val
                )
            elif k == "EMAIL" and not cur["email"]:
                cur["email"] = val
            elif k == "TEL" and not cur["phone"]:
                cur["phone"] = val
            elif k == "NOTE":
                cur["notes"] = val
    return cards
