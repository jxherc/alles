import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from services import skills_store

router = APIRouter(prefix="/api/skills")


@router.get("")
def list_skills(q: str = ""):
    return skills_store.search(q)


@router.get("/match")
def match(q: str, k: int = 3):
    """best skills for a request — drives auto-suggest in chat/agent."""
    return {"matches": skills_store.match_skills(q, k)}


@router.get("/catalog")
def catalog():
    """the built-in skill library, each marked installed or not."""
    from services import skills_catalog

    have = {s["slug"] for s in skills_store.list_skills()}
    return [{**it, "installed": it["slug"] in have} for it in skills_catalog.items()]


@router.get("/sources")
def sources():
    from services import skill_sources
    return skill_sources.list_sources()


@router.get("/sources/{sid}/browse")
def browse_source(sid: str):
    from services import skill_sources
    try:
        data = skill_sources.browse(sid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"couldn't reach this source: {e}")
    if data.get("kind") == "builtin":
        have = {s["slug"] for s in skills_store.list_skills()}
        data["skills"] = [{**it, "installed": it["slug"] in have} for it in data["skills"]]
    elif data.get("kind") == "github":
        # an imported github skill stores source == the blob url == the card's import_url
        srcs = {s.get("source") for s in skills_store.list_skills() if s.get("source")}
        # don't mutate the cached dict (browse caches github results ~600s)
        data = {**data, "skills": [{**it, "installed": it.get("import_url") in srcs} for it in data["skills"]]}
    return data


@router.get("/sources/{sid}/preview")
def preview_source(sid: str, path: str):
    from services import skill_sources
    try:
        return skill_sources.preview(sid, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"couldn't fetch skill: {e}")


class InstallBody(BaseModel):
    slugs: list[str] = []


@router.post("/install")
def install(body: InstallBody):
    """install one or more library skills into data/skills/."""
    from services import skills_catalog

    n = 0
    for slug in body.slugs or []:
        it = skills_catalog.get(slug)
        if it:
            skills_store.upsert_skill(it["name"], it["description"], it["when_to_use"], it["body"])
            n += 1
    return {"installed": n}


class GithubBody(BaseModel):
    url: str


@router.post("/import-github")
def import_github(body: GithubBody):
    """pull SKILL.md(s) from a github repo / folder / file url into data/skills/."""
    from services import skills_github

    try:
        return skills_github.import_from_github(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"github fetch failed: {e}")


class UploadItem(BaseModel):
    filename: str = ""
    text: str


class UploadBody(BaseModel):
    items: list[UploadItem] = []


@router.post("/upload")
def upload(body: UploadBody):
    """install uploaded SKILL.md files (their text is read client-side)."""
    imported, failed = [], 0
    for it in body.items:
        # a bare "SKILL.md" is a useless name — strip the extension, drop that sentinel
        fb = re.sub(r"\.(md|markdown|txt)$", "", (it.filename or "").strip(), flags=re.I)
        if fb.lower() == "skill":
            fb = ""
        try:
            imported.append(skills_store.upsert_from_md(it.text, fb or None)["slug"])
        except Exception:
            failed += 1
    return {"imported": imported, "failed": failed}


@router.get("/{slug}")
def get(slug: str):
    s = skills_store.get_skill(slug)
    if not s:
        raise HTTPException(404, "skill not found")
    return s


# 10c — marketplace-lite: export a skill to share, update a git-backed one from source
@router.get("/{slug}/export")
def export_skill(slug: str):
    md = skills_store.export_md(slug)
    if md is None:
        raise HTTPException(404, "skill not found")
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"content-disposition": f'attachment; filename="{slug}.SKILL.md"'},
    )


class PinBody(BaseModel):
    pinned: bool = True


@router.post("/{slug}/pin")
def pin(slug: str, body: PinBody):
    """pin a skill to the top of the list (sorts above usage/recency)."""
    if not skills_store.get_skill(slug):
        raise HTTPException(404, "skill not found")
    return {"pinned": skills_store.set_pinned(slug, body.pinned)}


@router.post("/{slug}/update")
def update_from_source(slug: str):
    try:
        r = skills_store.update_from_source(slug)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"update failed: {e}")
    if r.get("error") == "not found":
        raise HTTPException(404, "skill not found")
    return r


class SkillBody(BaseModel):
    name: str
    description: str = ""
    when_to_use: str = ""
    body: str = ""
    slug: str | None = None


@router.post("")
def create(body: SkillBody):
    try:
        return skills_store.upsert_skill(
            body.name, body.description, body.when_to_use, body.body, body.slug
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/{slug}")
def update(slug: str, body: SkillBody):
    try:
        return skills_store.upsert_skill(
            body.name, body.description, body.when_to_use, body.body, slug
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{slug}")
def delete(slug: str):
    if not skills_store.delete_skill(slug):
        raise HTTPException(404, "skill not found")
    return {"ok": True}
