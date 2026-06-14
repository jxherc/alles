"""
image generation via the OpenAI-style /v1/images/generations endpoint (the
de-facto standard — real OpenAI, plus most openai-compatible + local diffusion
servers speak it). returns raw PNG bytes; the caller drops them in the gallery.
providers that don't do images just error clearly.
"""
import base64
import httpx


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


async def generate(prompt: str, base_url: str, api_key: str, model: str = "",
                   size: str = "1024x1024", n: int = 1) -> list[bytes]:
    url = base_url.rstrip("/") + "/v1/images/generations"
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    payload = {"prompt": prompt, "n": max(1, min(4, int(n or 1))),
               "size": size or "1024x1024", "response_format": "b64_json"}
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
                    out.append(ir.content)
                except Exception:
                    pass
        return out
