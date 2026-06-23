"""3a - capability registry observability: one listing of everything the system can do.
also hosts the 5e extras status (optional native/ML capabilities)."""

from fastapi import APIRouter

from services import capabilities

router = APIRouter(prefix="/api/capabilities")


@router.get("/extras")
def list_extras():
    """5e - optional native/local-ML extras with availability + opt-in state."""
    from core.settings import load_settings
    from services import extras

    return {"extras": extras.status(load_settings())}


@router.get("")
def list_capabilities(kind: str = "", scope: str = "", tag: str = ""):
    capabilities.bootstrap()  # idempotent; ensures the catalog is populated
    caps = capabilities.all(kind=kind or None, scope=scope or None, tag=tag or None)
    rows = [
        {
            "name": c.name,
            "kind": c.kind,
            "description": c.description,
            "scope": c.scope,
            "tags": list(c.tags),
            "schema": c.schema,
        }
        for c in caps
    ]
    rows.sort(key=lambda r: (r["kind"], r["name"]))
    return {"capabilities": rows, "count": len(rows)}
