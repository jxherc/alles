"""
audio overview — turn a document / chat into a spoken script the client plays
through TTS. the model writes the prose; everything below is the deterministic
cleanup that turns its (markdown-y, label-prefixed) text into ordered,
TTS-ready segments [{speaker, text}]. kept pure + import-light so it's testable
without a model.
"""

import re

from services.llm import simple_complete  # re-exported so tests can monkeypatch it

_MAX_SEG = 600  # chars per segment — short enough to stream nicely through TTS
_MAX_SEGMENTS = 60
_HOSTS = ("Alex", "Sam")  # the two podcast voices we ask the model to use

# "Alex: ..." / "Sam: ..." (also tolerates a leading "**Alex:**" the model might add)
_LABEL = re.compile(r"^\s*\*{0,2}([A-Za-z][\w .'-]{0,24}?)\*{0,2}\s*[:：]\s*(.*)$")


def _strip_md(text: str) -> str:
    """drop code fences entirely, then flatten the inline markdown the model adds."""
    # remove fenced code blocks wholesale — never read code aloud
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            continue
        s = re.sub(r"^#{1,6}\s*", "", s)  # headings
        s = re.sub(r"^[-*+]\s+", "", s)  # bullets
        s = re.sub(r"^\d+\.\s+", "", s)  # ordered list markers
        s = s.replace("**", "").replace("`", "")
        s = re.sub(r"(?<!\w)[_*](\S[^_*]*?\S|\S)[_*](?!\w)", r"\1", s)  # _italic_ / *italic*
        out.append(s)
    return "\n".join(out)


def _chunk(text: str) -> list[str]:
    """split an over-long blob on sentence boundaries so no segment exceeds the cap."""
    text = text.strip()
    if len(text) <= _MAX_SEG:
        return [text] if text else []
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not sentence:
            continue
        if len(cur) + len(sentence) + 1 > _MAX_SEG and cur:
            parts.append(cur.strip())
            cur = sentence
        else:
            cur = (cur + " " + sentence).strip()
    if cur.strip():
        parts.append(cur.strip())
    # a single sentence longer than the cap → hard slice
    final = []
    for p in parts:
        while len(p) > _MAX_SEG:
            final.append(p[:_MAX_SEG])
            p = p[_MAX_SEG:]
        if p:
            final.append(p)
    return final


def _seg(speaker: str, text: str) -> list[dict]:
    return [{"speaker": speaker, "text": c} for c in _chunk(text)]


def format_script(raw: str, style: str) -> list[dict]:
    """raw model text → ordered [{speaker, text}] segments. podcast parses the
    Alex/Sam turns (falling back to alternating paragraphs if the model didn't
    label them); summary is one narrator, split by paragraph."""
    clean = _strip_md(raw or "")
    if not clean.strip():
        return []

    if style == "podcast":
        segs = []
        labeled = False
        cur_speaker, cur_text = None, ""
        for line in clean.splitlines():
            if not line.strip():
                continue
            m = _LABEL.match(line)
            if m:
                labeled = True
                spk, txt = m.group(1).strip(), m.group(2).strip()
                if spk == cur_speaker:
                    cur_text = (cur_text + " " + txt).strip()
                else:
                    if cur_speaker and cur_text.strip():
                        segs.extend(_seg(cur_speaker, cur_text))
                    cur_speaker, cur_text = spk, txt
            elif cur_speaker:  # continuation of the current turn
                cur_text = (cur_text + " " + line.strip()).strip()
        if cur_speaker and cur_text.strip():
            segs.extend(_seg(cur_speaker, cur_text))
        if labeled:
            return segs[:_MAX_SEGMENTS]
        # model ignored the host format → alternate the two voices by paragraph
        paras = [p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()]
        out = []
        for i, p in enumerate(paras):
            out.extend(_seg(_HOSTS[i % 2], p))
        return out[:_MAX_SEGMENTS]

    # summary (default): one narrator, one segment per paragraph
    paras = [p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()]
    if not paras:
        paras = [clean.strip()]
    out = []
    for p in paras:
        out.extend(_seg("Narrator", p))
    return out[:_MAX_SEGMENTS]


def build_messages(source_text: str, style: str) -> list[dict]:
    """the prompt that turns source material into a spoken overview."""
    source_text = (source_text or "")[:8000]
    if style == "podcast":
        sys = (
            "You are a scriptwriter. Turn the material into a short, lively two-host "
            f"podcast between {_HOSTS[0]} and {_HOSTS[1]}. Prefix every line with the "
            "speaker name and a colon (e.g. 'Alex: ...'). Conversational, ~8-14 turns, "
            "no stage directions, no markdown."
        )
    else:
        sys = (
            "You are a narrator. Write a clear, engaging spoken-word summary of the "
            "material as flowing paragraphs (no headings, no lists, no markdown). "
            "Aim for 4-8 short paragraphs that sound natural read aloud."
        )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": source_text},
    ]


async def generate(
    source_text: str, style: str, base_url: str, api_key: str, model: str
) -> list[dict]:
    """ask the model for the overview, then format it into TTS-ready segments."""
    raw = await simple_complete(
        build_messages(source_text, style), base_url, api_key, model, max_tokens=1200
    )
    return format_script(raw, style)
