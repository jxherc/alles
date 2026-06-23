"""
CardDAV two-way contact sync (iCloud / Google / any CardDAV server).

Mirrors caldav_sync: lazy + defensive, config in data/carddav.json. The sync core
takes an injectable client so it's fully unit-testable without a network; the real
client uses httpx (already a dep) to talk raw CardDAV (REPORT + PUT).
"""

import json
import re
import xml.etree.ElementTree as ET


def _cfg_path():
    from core.settings import data_dir

    return data_dir() / "carddav.json"


def load_cfg() -> dict:
    try:
        return json.loads(_cfg_path().read_text("utf-8"))
    except Exception:
        return {}


_INTERVALS = {"off": 0, "hourly": 3600, "daily": 86400}


def save_cfg(cfg: dict):
    cur = load_cfg()
    if not cfg.get("password") and cur.get("password"):
        cfg["password"] = cur["password"]  # UI doesn't echo the password back
    # interval + last_sync are sticky — connect/disconnect shouldn't wipe them
    for k in ("interval", "last_sync"):
        if k not in cfg and k in cur:
            cfg[k] = cur[k]
    p = _cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg), "utf-8")


def set_interval(v: str):
    if v not in _INTERVALS:
        return
    cfg = load_cfg()
    cfg["interval"] = v
    save_cfg(cfg)


def stamp_sync(now: float):
    cfg = load_cfg()
    cfg["last_sync"] = now
    save_cfg(cfg)


def due_for_sync(now: float) -> bool:
    cfg = load_cfg()
    if not (cfg.get("url") and cfg.get("username")):
        return False
    secs = _INTERVALS.get(cfg.get("interval", "off"), 0)
    if not secs:
        return False
    return (now - cfg.get("last_sync", 0)) >= secs


def status() -> dict:
    cfg = load_cfg()
    return {
        "connected": bool(cfg.get("url") and cfg.get("username") and cfg.get("password")),
        "url": cfg.get("url", ""),
        "username": cfg.get("username", ""),
        "interval": cfg.get("interval", "off"),
    }


def vcard_uid(text: str) -> str:
    m = re.search(r"^UID:(.+)$", text or "", re.MULTILINE)
    return m.group(1).strip() if m else ""


def parse_report(xml: str) -> list[dict]:
    """parse a CardDAV addressbook-query/multiget multistatus → [{href,etag,vcard}]."""
    out = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    for resp in root.iter():
        if not resp.tag.endswith("}response") and resp.tag != "response":
            continue
        href = etag = vcard = ""
        for el in resp.iter():
            tag = el.tag.split("}")[-1]
            if tag == "href" and not href:
                href = (el.text or "").strip()
            elif tag == "getetag" and not etag:
                etag = (el.text or "").strip().strip('"')
            elif tag == "address-data" and not vcard:
                vcard = (el.text or "").strip()
        if vcard:
            out.append({"href": href, "etag": etag, "vcard": vcard})
    return out


def _vc_esc(s) -> str:
    """vCard TEXT escaping + strip raw CR/LF so a field can't inject extra vcard lines."""
    return (
        str(s or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def build_vcard(contact: dict, uid: str) -> str:
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{uid}", f"FN:{_vc_esc(contact.get('name', ''))}"]
    if contact.get("email"):
        lines.append(f"EMAIL:{_vc_esc(contact['email'])}")
    if contact.get("phone"):
        lines.append(f"TEL:{_vc_esc(contact['phone'])}")
    if contact.get("company"):
        lines.append(f"ORG:{_vc_esc(contact['company'])}")
    lines.append("END:VCARD")
    return "\n".join(lines)


def sync(client=None, db=None) -> dict:
    import time

    from core.database import Contact, SessionLocal
    from services.vcard import parse_vcards

    _real = client is None  # only stamp last_sync for real (non-test) syncs
    if client is None:
        cfg = load_cfg()
        if not (cfg.get("url") and cfg.get("username")):
            return {"error": "not configured — add your CardDAV url + username first"}
        try:
            client = _RealClient(cfg)
        except Exception as e:
            return {"error": f"connect failed: {str(e)[:160]}"}

    own = db is None
    db = db or SessionLocal()
    pulled = pushed = 0
    try:
        # ── pull remote → local (match by vCard UID) ──
        try:
            entries = client.list()
        except Exception as e:
            return {"error": f"fetch failed: {str(e)[:160]}"}
        for e in entries:
            uid = vcard_uid(e["vcard"])
            if not uid:
                continue
            parsed = parse_vcards(e["vcard"])
            c = parsed[0] if parsed else {"name": "(no name)"}
            row = db.query(Contact).filter(Contact.carddav_uid == uid).first()
            if not row:
                row = Contact(name=c.get("name") or "(no name)", carddav_uid=uid)
                db.add(row)
            for k in ("name", "email", "phone", "company", "title", "address", "website"):
                if c.get(k):
                    setattr(row, k, c[k])
            row.carddav_href = e.get("href", "")
            row.carddav_etag = e.get("etag", "")
            pulled += 1

        # ── push local-only → remote ──
        locals_ = (
            db.query(Contact)
            .filter((Contact.carddav_uid == None) | (Contact.carddav_uid == ""))  # noqa: E711
            .all()
        )
        for c in locals_:
            uid = f"alles-{c.id}"
            text = build_vcard(
                {"name": c.name, "email": c.email, "phone": c.phone, "company": c.company}, uid
            )
            try:
                href = client.put(uid, text)
            except Exception:
                continue
            c.carddav_uid = uid
            c.carddav_href = href or ""
            pushed += 1

        db.commit()
    finally:
        if own:
            db.close()
    if _real:
        stamp_sync(time.time())
    return {"pulled": pulled, "pushed": pushed}


class _RealClient:
    """raw CardDAV over httpx — used when no client is injected. needs the user's server."""

    def __init__(self, cfg):
        self.url = cfg["url"].rstrip("/")
        self.auth = (cfg["username"], cfg.get("password", ""))

    def list(self):
        import httpx

        body = (
            '<?xml version="1.0"?><c:addressbook-query xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/>'
            "<c:address-data/></d:prop></c:addressbook-query>"
        )
        r = httpx.request(
            "REPORT",
            self.url,
            auth=self.auth,
            timeout=30,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=body,
        )
        r.raise_for_status()
        return parse_report(r.text)

    def put(self, uid, text):
        import httpx

        href = f"{self.url}/{uid}.vcf"
        r = httpx.put(
            href,
            auth=self.auth,
            timeout=30,
            headers={"Content-Type": "text/vcard"},
            content=text,
        )
        r.raise_for_status()
        return f"/{uid}.vcf"
