"""
YouTube → note: pull a video's transcript (no API key). Tries youtube-transcript-api
if installed, else scrapes the watch page's caption tracks → timedtext. Graceful
when transcripts are unavailable or YouTube blocks the server.
"""

import html as _html
import json
import re

import httpx

_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/v/|/live/)([A-Za-z0-9_-]{11})")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def extract_video_id(url: str):
    url = (url or "").strip()
    m = _ID_RE.search(url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    return None


async def fetch_transcript(video_id: str):
    """returns (title, transcript_text). raises ValueError if unavailable."""
    # 1) library, if it happens to be installed
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        parts = YouTubeTranscriptApi.get_transcript(video_id)
        text = re.sub(r"\s+", " ", " ".join(p.get("text", "") for p in parts)).strip()
        if text:
            return ("", text)
    except Exception:
        pass
    # 2) scrape the watch page → caption track → timedtext xml
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"user-agent": _UA, "accept-language": "en-US,en;q=0.9"},
    ) as c:
        r = await c.get(f"https://www.youtube.com/watch?v={video_id}")
        page = r.text
        title = ""
        mt = re.search(r"<title>(.*?)</title>", page, re.S)
        if mt:
            title = re.sub(r"\s*-\s*YouTube\s*$", "", _html.unescape(mt.group(1))).strip()
        m = re.search(r'"captionTracks":(\[.*?\])', page)
        if not m:
            raise ValueError("no captions found — this video may have transcripts disabled")
        try:
            tracks = json.loads(m.group(1))
        except Exception:
            raise ValueError("couldn't parse the caption list")
        track = next(
            (t for t in tracks if (t.get("languageCode") or "").startswith("en")),
            tracks[0] if tracks else None,
        )
        if not track or not track.get("baseUrl"):
            raise ValueError("no usable caption track")
        base = track["baseUrl"].replace("\\u0026", "&")
        # default timedtext is xml; json3 is more reliable when xml comes back empty
        tr = await c.get(base)
        segs = re.findall(r"<text[^>]*>(.*?)</text>", tr.text, re.S)
        text = " ".join(_html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\n", " ") for s in segs)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            sep = "&" if "?" in base else "?"
            tj = await c.get(base + sep + "fmt=json3")
            try:
                data = tj.json()
                chunks = []
                for ev in data.get("events", []):
                    for s in ev.get("segs", []) or []:
                        chunks.append(s.get("utf8", ""))
                text = re.sub(r"\s+", " ", "".join(chunks)).strip()
            except Exception:
                text = ""
        if not text:
            raise ValueError("the transcript came back empty")
        return (title, text)
