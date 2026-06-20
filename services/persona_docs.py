"""10d — knowledge files attached to a persona.

Each attached doc's text is indexed in the shared 1c text index under kind="persona:<id>"; the
PersonaDoc row keeps the title. At run time `knowledge_block` pulls the chunks most relevant to the
user's message so a custom assistant can answer from its own files.
"""

from core.database import PersonaDoc
from services import textindex


def _kind(pid: str) -> str:
    return f"persona:{pid}"


def attach(db, pid: str, title: str, content: str) -> PersonaDoc:
    doc = PersonaDoc(persona_id=pid, title=(title or "untitled").strip() or "untitled")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    textindex.index(db, _kind(pid), doc.id, content or "")
    return doc


def list_docs(db, pid: str):
    return (
        db.query(PersonaDoc)
        .filter(PersonaDoc.persona_id == pid)
        .order_by(PersonaDoc.created_at.asc())
        .all()
    )


def detach(db, pid: str, doc_id: str) -> bool:
    doc = db.get(PersonaDoc, doc_id)
    if not doc or doc.persona_id != pid:
        return False
    textindex.remove(db, _kind(pid), doc_id)
    db.delete(doc)
    db.commit()
    return True


def purge(db, pid: str):
    """drop every knowledge doc + its index chunks for a persona (called on persona delete)."""
    for d in list_docs(db, pid):
        textindex.remove(db, _kind(pid), d.id)
        db.delete(d)
    db.commit()


def knowledge_block(db, pid: str, query: str, k: int = 5) -> str:
    """the most relevant attached-file chunks for a query, joined — '' if none match."""
    hits = textindex.search(db, query, _kind(pid), k)
    return "\n\n".join(h["chunk"] for h in hits) if hits else ""
