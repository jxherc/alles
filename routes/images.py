import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Message, ModelEndpoint, Session, get_db
from services.photo_records import format_photo, save_generated_photos

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

    try:
        photos = save_generated_photos(db, imgs, body.prompt)
    except OSError as exc:
        raise HTTPException(503, "generated image couldn't be saved; please retry") from exc
    if not photos:
        raise HTTPException(502, "generated image couldn't be saved")
    return {"images": [format_photo(photo) for photo in photos]}


class ChatImageBody(BaseModel):
    session_id: str
    prompt: str
    model: str = ""
    endpoint_id: str = ""
    size: str = "1024x1024"
    n: int = 1


# POST /api/images/chat — generate from inside a chat thread. drops the image into
# the conversation, saves it to Photos, tries to file it in Docs, and persists
# the turn so it survives a reload. returns the assistant markdown the UI renders.
@router.post("/chat")
async def generate_in_chat(body: ChatImageBody, db: DbSession = Depends(get_db)):
    if not body.prompt.strip():
        raise HTTPException(400, "empty prompt")
    from services import incognito

    s = incognito.get_session(body.session_id) or db.get(Session, body.session_id)
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

    try:
        saved = save_generated_photos(db, imgs, body.prompt)
    except OSError as exc:
        raise HTTPException(503, "generated image couldn't be saved; please retry") from exc
    if not saved:
        raise HTTPException(502, "generated image couldn't be saved")

    img_md = "\n\n".join(f"![{alt}](/api/photos/original/{p.id})" for p in saved)

    # Docs is an extra copy; its outage must not discard the generated image or chat turn.
    from services import notes_vault

    try:
        note = notes_vault.create(
            title=title,
            content=f"# {title}\n\n*image · {body.model or ep.name}*\n\n{img_md}\n",
            tags=["image"],
        )
    except OSError:
        note = None
    if note:
        try:
            from services import personal_index

            personal_index.index_record(db, "note", note["id"])
        except Exception:
            pass

    note_id = note["id"] if note else None
    note_status = "✓ saved to notes" if note else "couldn't save to notes"
    assistant_md = f"{img_md}\n\n`{note_status}` · {title}"

    db.add(Message(session_id=s.id, role="user", content=body.prompt))
    db.add(
        Message(
            session_id=s.id,
            role="assistant",
            content=assistant_md,
            meta=json.dumps({"model": body.model, "image": True, "note_id": note_id}),
        )
    )
    if not s.name or s.name == "new chat":
        s.name = title
    s.message_count = (s.message_count or 0) + 2  # we added BOTH a user + an assistant message
    s.last_message_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    return {
        "content": assistant_md,
        "doc_id": note_id,  # frontend uses this as a "saved" flag + to rename the chat
        "doc_title": title,
        "images": [{"id": p.id, "original": f"/api/photos/original/{p.id}"} for p in saved],
    }
