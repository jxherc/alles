"""
image generation via the OpenAI-style /v1/images/generations endpoint (the
de-facto standard — real OpenAI, plus most openai-compatible + local diffusion
servers speak it). returns raw PNG bytes; the caller drops them in the gallery.
providers that don't do images just error clearly.
"""

import base64
import re
import httpx

# which model ids are image-generation models — used to split a provider's model
# list into chat vs image so the gallery's model picker only shows the image ones.
# broad on purpose ("all the possible ones"): covers the common families across
# OpenAI, Google, and the OSS/local diffusion world. a custom id can still be typed.
_IMAGE_RE = re.compile(
    r"dall-?e|gpt-image|imagen|image-?gen|"
    r"stable-?diffusion|sdxl|\bsd[-_ ]?(?:xl|3|3\.5|2|1\.5|turbo)\b|"
    r"flux|playground-v|kandinsky|kolors|hunyuan-?(?:image|dit)|qwen-?image|"
    r"recraft|ideogram|seedream|seededit|aura-?flow|pixart|cogview|janus|"
    r"omnigen|\bsana\b|hidream|wuerstchen|midjourney|photon|"
    r"grok.*image|titan-image|nova-canvas",
    re.I,
)


def is_image_model(mid: str) -> bool:
    return bool(_IMAGE_RE.search(mid or ""))


def image_models(models) -> list[str]:
    """the image-gen subset of a model-id list, order preserved."""
    return [m for m in (models or []) if is_image_model(m)]


def _b64_images(data: dict) -> list[bytes]:
    """pull b64_json images out of an images response (the testable bit)."""
    out = []
    for item in (data or {}).get("data", []):
        if item.get("b64_json"):
            try:
                out.append(base64.b64decode(item["b64_json"]))
            except Exception:
                pass
    return out


async def generate(
    prompt: str, base_url: str, api_key: str, model: str = "", size: str = "1024x1024", n: int = 1
) -> list[bytes]:
    url = base_url.rstrip("/") + "/v1/images/generations"
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    payload = {
        "prompt": prompt,
        "n": max(1, min(4, int(n or 1))),
        "size": size or "1024x1024",
        "response_format": "b64_json",
    }
    if model:
        payload["model"] = model

    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"image generation failed (HTTP {r.status_code}): {r.text[:200]}")
        data = r.json()
        out = _b64_images(data)
        if out:
            return out
        # some servers return urls instead of b64 — fetch them in the same client
        for item in data.get("data", []):
            if item.get("url"):
                try:
                    ir = await c.get(item["url"])
                    if (
                        ir.status_code < 400 and ir.content
                    ):  # don't pass an error page off as an image
                        out.append(ir.content)
                except Exception:
                    pass
        return out
