import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, ModelEndpoint, Photo, Session, Message, Note
from services import photos_store as ps
from routes.photos import _fmt

router = APIRouter(prefix="/api/images")


def _alt(s: str) -> str:
    # keep the markdown image alt from breaking on brackets/newlines
    return (s or "image").replace("[", "(").replace("]", ")").replace("\n", " ").strip()[:80]


class GenBody(BaseModel):
    prompt: str
    model: str = ""  # e.g. dall-e-3 / gpt-image-1 / a local diffusion model
    endpoint_id: str = ""  # blank → first enabled endpoint
    size: str = "1024x1024"
    n: int = 1


@router.post("/generate")
async def generate_image(body: GenBody, db: DbSession = Depends(get_db)):
    if not body.prompt.strip():
        raise HTTPException(400, "empty prompt")
    ep = (
        db.get(ModelEndpoint, body.endpoint_id)
        if body.endpoint_id
        else db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    )
    if not ep:
        raise HTTPException(400, "no model endpoint configured")

    from services.imagegen import generate

    try:
        imgs = await generate(body.prompt, ep.base_url, ep.api_key, body.model, body.size, body.n)
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    if not imgs:
        raise HTTPException(
            502, "the endpoint returned no image (does it support image generation?)"
        )

    saved = []
    for i, raw in enumerate(imgs):
        try:
            info = ps.import_image(raw, f"generated-{i + 1}.png")
        except ValueError:
            continue
        p = Photo(
            filename=info["filename"],
            thumb=info["thumb"],
            original_name=(body.prompt[:60] or "generated") + ".png",
            width=info["width"],
            height=info["height"],
            taken_at=info["taken_at"],
            exif=info["exif"],
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        saved.append(_fmt(p))
    if not saved:
        raise HTTPException(502, "generated image couldn't be saved")
    return {"images": saved}


class ChatImageBody(BaseModel):
    session_id: str
    prompt: str
    model: str = ""
    endpoint_id: str = ""
    size: str = "1024x1024"
    n: int = 1


# POST /api/images/chat — generate from inside a chat thread. drops the image into
# the conversation, saves it to the gallery AND files it as a document, and persists
# the turn so it survives a reload. returns the assistant markdown the UI renders.
@router.post("/chat")
async def generate_in_chat(body: ChatImageBody, db: DbSession = Depends(get_db)):
    if not body.prompt.strip():
        raise HTTPException(400, "empty prompt")
    s = db.get(Session, body.session_id)
    if not s:
        raise HTTPException(404, "session not found")
    ep = (
        db.get(ModelEndpoint, body.endpoint_id)
        if body.endpoint_id
        else db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    )
    if not ep:
        raise HTTPException(400, "no model endpoint configured")

    from services.imagegen import generate

    try:
        imgs = await generate(body.prompt, ep.base_url, ep.api_key, body.model, body.size, body.n)
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    if not imgs:
        raise HTTPException(
            502, "the endpoint returned no image (does it support image generation?)"
        )

    alt = _alt(body.prompt)
    title = body.prompt.strip()[:60] or "generated image"

    # incognito → leave no trace anywhere: don't touch the gallery/documents/history,
    # just inline the image as a data-uri so it shows in the (ephemeral) thread.
    if s.incognito:
        import base64

        md = "\n\n".join(
            f"![{alt}](data:image/png;base64,{base64.b64encode(b).decode()})" for b in imgs
        )
        return {"content": md, "doc_id": None, "doc_title": title, "images": []}

    saved = []
    for i, raw in enumerate(imgs):
        try:
            info = ps.import_image(raw, f"generated-{i + 1}.png")
        except Exception:
            continue  # provider handed back junk/non-image bytes for this one — skip it
        saved.append(
            Photo(
                filename=info["filename"],
                thumb=info["thumb"],
                original_name=(body.prompt[:60] or "generated") + ".png",
                width=info["width"],
                height=info["height"],
                taken_at=info["taken_at"],
                exif=info["exif"],
            )
        )
    if not saved:
        raise HTTPException(502, "generated image couldn't be saved")
    for p in saved:
        db.add(p)
    db.commit()
    for p in saved:
        db.refresh(p)

    img_md = "\n\n".join(f"![{alt}](/api/photos/original/{p.id})" for p in saved)

    # file it in docs (notes — the live docs app) too so it's easy to find later
    note = Note(
        title=title,
        content=f"# {title}\n\n*image · {body.model or ep.name}*\n\n{img_md}\n",
        tags="image",
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    assistant_md = f"{img_md}\n\n`✓ saved to notes` · {title}"

    db.add(Message(session_id=s.id, role="user", content=body.prompt))
    db.add(
        Message(
            session_id=s.id,
            role="assistant",
            content=assistant_md,
            meta=json.dumps({"model": body.model, "image": True, "note_id": note.id}),
        )
    )
    if not s.name or s.name == "new chat":
        s.name = title
    s.message_count = (s.message_count or 0) + 1
    s.last_message_at = datetime.utcnow()
    db.commit()

    return {
        "content": assistant_md,
        "doc_id": note.id,  # frontend uses this as a "saved" flag + to rename the chat
        "doc_title": title,
        "images": [{"id": p.id, "original": f"/api/photos/original/{p.id}"} for p in saved],
    }
