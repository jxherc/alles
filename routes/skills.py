from fastapi import APIRouter, HTTPException
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


@router.get("/{slug}")
def get(slug: str):
    s = skills_store.get_skill(slug)
    if not s:
        raise HTTPException(404, "skill not found")
    return s


class SkillBody(BaseModel):
    name: str
    description: str = ""
    when_to_use: str = ""
    body: str = ""
    slug: str | None = None


@router.post("")
def create(body: SkillBody):
    try:
        return skills_store.upsert_skill(body.name, body.description, body.when_to_use, body.body, body.slug)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/{slug}")
def update(slug: str, body: SkillBody):
    try:
        return skills_store.upsert_skill(body.name, body.description, body.when_to_use, body.body, slug)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{slug}")
def delete(slug: str):
    if not skills_store.delete_skill(slug):
        raise HTTPException(404, "skill not found")
    return {"ok": True}
