"""What each model really supports for reasoning effort.

Pure functions. Provider catalog metadata wins; one small name table covers
models whose catalogs say nothing. Unknown models get no levels.
"""

import re

PROVIDER_LEVELS = ("low", "medium", "high", "xhigh", "max")
_LMH = ("low", "medium", "high")
_NO_XHIGH = ("low", "medium", "high", "max")
# claude models that think only through an explicit token budget (no effort field)
_BUDGET_LEVELS = ("high", "xhigh", "max")
_BUDGET_NAMES = ("3-7", "opus-4", "sonnet-4", "haiku-4", "opus4", "sonnet4")

# names that think, for pi: a guess, pi clamps a level the model doesn't take
_THINKS = re.compile(
    r"(^|[^a-z0-9])(o1|o3|o4)([^a-z0-9]|$)|gpt-5|gpt5|gemini-(2\.5|[3-9])|deepseek-(r1|reasoner|v3\.[1-9]|v[4-9])"
    r"|qwen3|qwq|thinking|reason|kimi-k2|glm-(4\.[5-9]|[5-9])|grok-(3-mini|[4-9])|minimax-m|magistral"
)


def _name(model: str) -> str:
    return (model or "").lower().split("/")[-1].replace(".", "-")


def _ordered(values) -> list[str]:
    wanted = {str(v).lower() for v in values or [] if isinstance(v, str)}
    return [level for level in PROVIDER_LEVELS if level in wanted]


def _flag(data, *path):
    """True/False when metadata states it, None when the shape is missing."""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data if isinstance(data, bool) else None


def _anthropic_name_levels(name: str) -> tuple[str, ...]:
    if re.search(r"(fable|mythos)-?5", name):
        return _NO_XHIGH if "preview" in name else PROVIDER_LEVELS
    m = re.search(r"(opus|sonnet|haiku)-(\d)(?!\d)(?:-(\d{1,2})(?!\d))?", name)
    if not m:
        return ()
    family, major, minor = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    if major >= 5:
        return PROVIDER_LEVELS
    if major == 4 and family == "opus":
        if minor >= 7:
            return PROVIDER_LEVELS
        if minor == 6:
            return _NO_XHIGH
        if minor == 5:
            return _LMH
    if major == 4 and family == "sonnet":
        if minor >= 7:
            return PROVIDER_LEVELS
        if minor == 6:
            return _NO_XHIGH
    return ()


def _anthropic(model: str, metadata: dict) -> tuple[list[str], str]:
    """(levels, api): api is "effort" (output_config.effort), "budget" or ""."""
    caps = metadata.get("capabilities")
    if isinstance(caps, dict):
        effort = caps.get("effort")
        if _flag(effort, "supported") is True:
            levels = [
                level for level in PROVIDER_LEVELS if _flag(effort, level, "supported") is True
            ]
            return (levels, "effort") if levels else ([], "")
        if _flag(effort, "supported") is False:
            if _flag(caps, "thinking", "types", "enabled", "supported") is True:
                return list(_BUDGET_LEVELS), "budget"
            return [], ""
    name = _name(model)
    levels = _anthropic_name_levels(name)
    if levels:
        return list(levels), "effort"
    if any(part in name for part in _BUDGET_NAMES):
        return list(_BUDGET_LEVELS), "budget"
    return [], ""


def anthropic_effort_api(model: str, metadata: dict | None = None) -> str:
    return _anthropic(model, metadata if isinstance(metadata, dict) else {})[1]


def anthropic_budget_thinking(model: str, metadata: dict | None = None) -> bool:
    """Whether a request may ask for extended thinking with a token budget."""
    metadata = metadata if isinstance(metadata, dict) else {}
    caps = metadata.get("capabilities")
    known = _flag(caps, "thinking", "types", "enabled", "supported")
    if known is not None:
        return known
    name = _name(model)
    return any(part in name for part in _BUDGET_NAMES)


def _openai_levels(name: str) -> list[str]:
    if re.match(r"o1-(mini|preview)", name) or "chat" in name:
        return []
    if re.match(r"o[134](-|$)", name):
        return list(_LMH)
    if "gpt-5-pro" in name:
        return ["high"]
    m = re.search(r"gpt-?(\d{1,2})(?:-(\d{1,2})(?!\d))?", name)
    if not m or int(m.group(1)) < 5:
        return []
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    if major >= 6 or minor >= 2:
        return [*_LMH, "xhigh"]
    return list(_LMH)


def _gemini_levels(name: str) -> list[str]:
    if re.search(r"image|tts|embed|live", name):
        return []
    return list(_LMH) if re.search(r"gemini-(2-5|[3-9])", name) else []


def _from_metadata(metadata: dict) -> list[str] | None:
    """Levels the provider's own catalog states, or None when it says nothing."""
    reasoning = metadata.get("reasoning")
    if isinstance(reasoning, dict):
        levels = _ordered(reasoning.get("supported_efforts"))
        if levels:
            return levels
    params = metadata.get("supported_parameters")
    if isinstance(params, list):
        names = {str(p).lower() for p in params}
        return list(_LMH) if names & {"reasoning", "reasoning_effort"} else []
    thinking = metadata.get("thinking")
    if isinstance(thinking, bool):
        return list(_LMH) if thinking else []
    return None


def effort_levels(provider: str, model: str, metadata: dict | None = None) -> list[str]:
    """Provider effort levels (subset of low..max) this model takes, or []."""
    metadata = metadata if isinstance(metadata, dict) else {}
    if provider == "anthropic":
        return _anthropic(model, metadata)[0]
    stated = _from_metadata(metadata)
    if stated is not None:
        return stated
    name = _name(model)
    if provider == "openai":
        return _openai_levels(name)
    if provider == "gemini":
        return _gemini_levels(name)
    return []


def metadata_for(endpoint, model: str) -> dict:
    """The catalog metadata an endpoint stored for one model, or {}."""
    try:
        value = endpoint.model_metadata_dict().get(model)
    except (AttributeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def thinks(model: str) -> bool:
    name = (model or "").lower().split("/")[-1]
    if "claude" in name:
        return not re.search(r"claude-(instant|2|3-5|3\.5|3-(opus|sonnet|haiku))", name)
    return bool(_THINKS.search(name))
