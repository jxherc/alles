from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, ModelEndpoint, Photo
from services import photos_store as ps
from routes.photos import _fmt

router = APIRouter(prefix="/api/images")


class GenBody(BaseModel):
    prompt: str
    model: str = ""          # e.g. dall-e-3 / gpt-image-1 / a local diffusion model
    endpoint_id: str = ""    # blank → first enabled endpoint
    size: str = "1024x1024"
    n: int = 1


@router.post("/generate")
async def generate_image(body: GenBody, db: DbSession = Depends(get_db)):
    if not body.prompt.strip():
        raise HTTPException(400, "empty prompt")
    ep = (db.get(ModelEndpoint, body.endpoint_id) if body.endpoint_id
          else db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first())
    if not ep:
        raise HTTPException(400, "no model endpoint configured")

    from services.imagegen import generate
    try:
        imgs = await generate(body.prompt, ep.base_url, ep.api_key, body.model, body.size, body.n)
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    if not imgs:
        raise HTTPException(502, "the endpoint returned no image (does it support image generation?)")

    saved = []
    for i, raw in enumerate(imgs):
        try:
            info = ps.import_image(raw, f"generated-{i + 1}.png")
        except ValueError:
            continue
        p = Photo(filename=info["filename"], thumb=info["thumb"],
                  original_name=(body.prompt[:60] or "generated") + ".png",
                  width=info["width"], height=info["height"],
                  taken_at=info["taken_at"], exif=info["exif"])
        db.add(p); db.commit(); db.refresh(p)
        saved.append(_fmt(p))
    if not saved:
        raise HTTPException(502, "generated image couldn't be saved")
    return {"images": saved}
