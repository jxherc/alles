"""shared bits for the research engine: thinking-tag stripping + quality filter."""

import re

# matches paired reasoning blocks, whatever flavor the model emits
_THINK_PAIR = re.compile(r"<(think|thinking|reason|reasoning)>.*?</\1>", re.S | re.I)


def strip_think(text):
    """drop reasoning tokens from an LLM reply so callers see only the answer.

    handles three real-world shapes:
      - paired  <think>...</think>
      - a bare trailing </think> after un-tagged reasoning (some r1 distills)
      - an unclosed <think> with no answer after it
    None passes through (callers pass Optional results and branch on None)."""
    if text is None:
        return None
    t = _THINK_PAIR.sub("", text)
    low = t.lower()
    # reasoning then a lone </think>, no opening tag — keep what's after it
    if "<think" not in low and "</think>" in low:
        idx = low.rfind("</think>")
        t = t[idx + len("</think>") :]
    # opening tag with nothing closing it — everything after is reasoning, drop it
    elif "<think" in low and "</think>" not in low:
        t = t[: low.find("<think")]
    return t.strip()


# back-compat alias — odysseus callers import strip_thinking
def strip_thinking(text):
    return strip_think(text)


# markers that mean the extraction is boilerplate / a refusal / empty.
# phrases not bare words, so a page literally about cookies/copyright still counts.
LOW_QUALITY_MARKERS = [
    "insufficient to",
    "content is insufficient",
    "no substantive data",
    "does not contain",
    "not relevant to",
    "no relevant information",
    "unable to extract",
    "completely unrelated",
    "boilerplate",
    "footer text",
    "cookie consent",
    "cookie banner",
    "cookie notice",
    "copyright notice",
    "copyright footer",
    "all rights reserved",
]


def is_low_quality(summary: str) -> bool:
    try:
        if not isinstance(summary, str) or not summary:
            return True
        low = summary.lower()
        return any(m in low for m in LOW_QUALITY_MARKERS)
    except Exception:
        return False  # fail open — better to keep a finding than lose it
