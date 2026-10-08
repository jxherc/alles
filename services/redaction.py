import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_NAME = re.compile(
    r"(^|[_-])(api[_-]?key|token|secret|password|passwd|authorization|credential|auth)($|[_-])",
    re.IGNORECASE,
)


def sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME.search(str(name or "")))


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return "[redacted invalid url]"
    if not parsed.scheme or not host:
        return value
    shown_host = f"[{host}]" if ":" in host else host
    if port is not None:
        shown_host += f":{port}"
    if parsed.username is not None or parsed.password is not None:
        shown_host = f"***@{shown_host}"
    query = urlencode(
        [(key, "***" if sensitive_name(key) else item) for key, item in parse_qsl(parsed.query)],
        doseq=True,
    )
    fragment = "***" if parsed.fragment else ""
    return urlunsplit((parsed.scheme, shown_host, parsed.path, query, fragment))


def redact_mapping(value):
    if isinstance(value, dict):
        return {
            str(key): "***" if sensitive_name(str(key)) else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str) and "://" in value:
        return redact_url(value)
    return value


def redact_args(args: list[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for raw in args:
        value = str(raw)
        if redact_next:
            result.append("***")
            redact_next = False
            continue
        if "=" in value:
            key, _item = value.split("=", 1)
            if sensitive_name(key.lstrip("-")):
                result.append(f"{key}=***")
                continue
        result.append(value)
        if value.startswith("-") and sensitive_name(value.lstrip("-")):
            redact_next = True
    return result
