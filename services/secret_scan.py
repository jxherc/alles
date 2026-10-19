"""spot secrets in what the owner types to a coding agent and swap them for placeholders.

the agent sees {{secret:NAME}}; alles's pi extension puts the real value back only inside the
tool call that uses it and hides it again in anything the tool prints. two ways in:
- known key shapes (openai, anthropic, github, aws, google, slack, stripe, jwt, private keys…)
- anything wrapped in ||double bars||, like a chat spoiler: the bars mean "hidden", whatever is
  inside. no spaces right inside the bars, so a shell `a || b` is left alone
"""

from __future__ import annotations

import math
import re

# (name prefix, pattern); order matters, the first match names it
KNOWN = [
    ("openai_key", r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("github_token", r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}"),
    ("gitlab_token", r"glpat-[A-Za-z0-9_-]{20,}"),
    ("aws_key", r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    ("google_key", r"AIza[0-9A-Za-z_-]{35}"),
    ("slack_token", r"xox[abposr]-[A-Za-z0-9-]{10,}"),
    ("stripe_key", r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{20,}"),
    ("huggingface_token", r"hf_[A-Za-z0-9]{30,}"),
    ("npm_token", r"npm_[A-Za-z0-9]{36}"),
    ("jwt", r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
]
_KNOWN = [(name, re.compile(pattern)) for name, pattern in KNOWN]
# the bars stand on their own (space, start, "=", ":" or a quote around them), so shell code
# like cmd||exit is left alone
_MARKED = re.compile(r"(?<![^\s=:(\"'])\|\|(\S(?:[^|\n]*\S)?)\|\|(?=$|[\s.,;:!?)\"'])")
# key=value style: password=..., api_key: "...", token ...
_ASSIGNED = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|bearer)\b\s*[:=]?\s*[\"']?([A-Za-z0-9_\-./+=]{16,})"
)


def _entropy(value: str) -> float:
    counts = {c: value.count(c) for c in set(value)}
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def _looks_random(value: str) -> bool:
    kinds = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[_\-./+=]"))
    return len(value) >= 16 and kinds >= 2 and _entropy(value) >= 3.3


def mask(text: str, known: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """returns the text with secrets replaced, and every secret by name (old ones reused)."""
    secrets = dict(known or {})
    by_value = {value: name for name, value in secrets.items()}

    def name_for(prefix: str, value: str) -> str:
        if value in by_value:
            return by_value[value]
        count = sum(1 for name in secrets if name.startswith(prefix)) + 1
        name = f"{prefix}_{count}"
        secrets[name] = value
        by_value[value] = name
        return name

    def swap(value: str, prefix: str) -> str:
        return "{{secret:" + name_for(prefix, value) + "}}"

    out = _MARKED.sub(lambda m: swap(m.group(1), "secret"), text)
    for prefix, pattern in _KNOWN:
        out = pattern.sub(lambda m, p=prefix: swap(m.group(0), p), out)
    out = _ASSIGNED.sub(
        lambda m: (
            m.group(0).replace(m.group(1), swap(m.group(1), "secret"))
            if "{{secret:" not in m.group(0) and _looks_random(m.group(1))
            else m.group(0)
        ),
        out,
    )
    # anything already known that shows up again, in any shape
    for value, name in sorted(by_value.items(), key=lambda item: -len(item[0])):
        out = out.replace(value, "{{secret:" + name + "}}")
    return out, secrets


def hide(text: str, secrets: dict[str, str]) -> str:
    """the last line of defense for anything alles shows or saves."""
    for name, value in sorted(secrets.items(), key=lambda item: -len(item[1])):
        if value:
            text = text.replace(value, "{{secret:" + name + "}}")
    return text
