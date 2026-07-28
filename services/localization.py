"""Validated local interface catalogs and independent locale preference options."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "static" / "locales"
CATALOG_MANIFEST_PATH = CATALOG_DIR / "manifest.json"
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}", re.IGNORECASE)

REGION_OPTIONS = (
    {"value": "", "label": "automatic"},
    {"value": "TW", "label": "Taiwan"},
    {"value": "US", "label": "United States"},
    {"value": "FR", "label": "France"},
    {"value": "ES", "label": "Spain"},
    {"value": "CN", "label": "China"},
    {"value": "JP", "label": "Japan"},
    {"value": "KR", "label": "South Korea"},
)

TIMEZONE_OPTIONS = (
    {"value": "", "label": "automatic"},
    {"value": "Asia/Taipei", "label": "Asia/Taipei"},
    {"value": "Europe/Paris", "label": "Europe/Paris"},
    {"value": "America/New_York", "label": "America/New_York"},
    {"value": "UTC", "label": "UTC"},
)

CURRENCY_OPTIONS = (
    {"value": "", "label": "automatic"},
    {"value": "TWD", "label": "TWD"},
    {"value": "USD", "label": "USD"},
    {"value": "EUR", "label": "EUR"},
    {"value": "CNY", "label": "CNY"},
    {"value": "JPY", "label": "JPY"},
    {"value": "KRW", "label": "KRW"},
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate catalog key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read localization catalog {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"localization catalog {path.name} must contain an object")
    return payload


def _placeholders(value: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(value))


def load_catalog_manifest(path: Path | None = None) -> dict:
    manifest_path = Path(path or CATALOG_MANIFEST_PATH)
    payload = _read_json(manifest_path)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported localization manifest schema")
    source_revision = str(payload.get("source_revision") or "").strip()
    languages = payload.get("languages")
    if not source_revision or not isinstance(languages, list) or not languages:
        raise ValueError("localization manifest needs a source revision and languages")

    seen: set[str] = set()
    normalized: list[dict] = []
    for raw in languages:
        if not isinstance(raw, dict):
            raise ValueError("localization language metadata must contain objects")
        language = str(raw.get("id") or "").strip()
        if not language or language in seen:
            raise ValueError("localization language IDs must be unique and non-empty")
        seen.add(language)
        direction = raw.get("direction")
        if direction not in {"ltr", "rtl"}:
            raise ValueError(f"localization language {language} has an invalid direction")
        categories = raw.get("plural_categories")
        if (
            not isinstance(categories, list)
            or not categories
            or "other" not in categories
            or any(not isinstance(item, str) or not item for item in categories)
            or len(set(categories)) != len(categories)
        ):
            raise ValueError(f"localization language {language} has invalid plural categories")
        release_state = str(raw.get("release_state") or "").strip()
        if not release_state:
            raise ValueError(f"localization language {language} needs a release state")
        normalized.append(
            {
                "id": language,
                "label": str(raw.get("label") or "").strip(),
                "english_name": str(raw.get("english_name") or "").strip(),
                "direction": direction,
                "plural_categories": list(categories),
                "release_state": release_state,
            }
        )
    if not normalized[0]["id"] == "en" or not normalized[0]["release_state"] == "available":
        raise ValueError("English must be the first available fallback catalog")
    coverage = payload.get("coverage_contract")
    if not isinstance(coverage, dict):
        raise ValueError("localization manifest needs a coverage contract")
    flows = coverage.get("localized_core_flows")
    boundaries = coverage.get("source_language_boundaries")
    if not isinstance(flows, list) or not flows:
        raise ValueError("localization coverage needs named core flows")
    if (
        not isinstance(boundaries, list)
        or not boundaries
        or any(not isinstance(item, str) or not item.strip() for item in boundaries)
    ):
        raise ValueError("localization coverage needs explicit source-language boundaries")
    flow_ids: set[str] = set()
    normalized_flows: list[dict] = []
    for raw in flows:
        if not isinstance(raw, dict):
            raise ValueError("localization core flows must contain objects")
        flow_id = str(raw.get("id") or "").strip()
        sources = raw.get("sources")
        prefixes = raw.get("key_prefixes")
        if not flow_id or flow_id in flow_ids:
            raise ValueError("localization core-flow IDs must be unique and non-empty")
        flow_ids.add(flow_id)
        if (
            not isinstance(sources, list)
            or not sources
            or any(
                not isinstance(item, str)
                or not item.startswith("static/")
                or ".." in Path(item).parts
                for item in sources
            )
        ):
            raise ValueError(f"localization core flow {flow_id} has invalid sources")
        if (
            not isinstance(prefixes, list)
            or not prefixes
            or any(not isinstance(item, str) or not item.endswith(".") for item in prefixes)
        ):
            raise ValueError(f"localization core flow {flow_id} has invalid key prefixes")
        normalized_flows.append(
            {"id": flow_id, "sources": list(sources), "key_prefixes": list(prefixes)}
        )
    return {
        "schema_version": 1,
        "source_revision": source_revision,
        "languages": normalized,
        "coverage_contract": {
            "localized_core_flows": normalized_flows,
            "source_language_boundaries": [item.strip() for item in boundaries],
        },
    }


def _validate_catalog_shape(catalog: dict, language: dict, source_revision: str) -> None:
    language_id = language["id"]
    if catalog.get("schema_version") != 1 or catalog.get("language") != language_id:
        raise ValueError(f"catalog {language_id} has invalid identity metadata")
    if catalog.get("source_revision") != source_revision:
        raise ValueError(f"catalog {language_id} has a stale source revision")
    review = catalog.get("review")
    if not isinstance(review, dict) or review.get("state") != "reviewed":
        raise ValueError(f"catalog {language_id} has not completed editorial review")
    if not str(review.get("reviewer") or "").strip():
        raise ValueError(f"catalog {language_id} needs a reviewer")
    try:
        date.fromisoformat(str(review.get("reviewed_on") or ""))
    except ValueError as exc:
        raise ValueError(f"catalog {language_id} needs a valid review date") from exc
    messages = catalog.get("messages")
    plurals = catalog.get("plurals")
    if (
        not isinstance(messages, dict)
        or not messages
        or any(
            not isinstance(key, str) or not isinstance(value, str) or not value
            for key, value in messages.items()
        )
    ):
        raise ValueError(f"catalog {language_id} has invalid messages")
    if not isinstance(plurals, dict) or not plurals:
        raise ValueError(f"catalog {language_id} has invalid plurals")
    expected_categories = set(language["plural_categories"])
    for key, forms in plurals.items():
        if not isinstance(key, str) or not isinstance(forms, dict):
            raise ValueError(f"catalog {language_id} has an invalid plural entry")
        if set(forms) != expected_categories:
            raise ValueError(f"catalog {language_id} plural {key} has incorrect categories")
        if any(not isinstance(value, str) or not value for value in forms.values()):
            raise ValueError(f"catalog {language_id} plural {key} has an empty form")


def validate_catalogs(catalog_dir: Path | None = None, manifest_path: Path | None = None) -> dict:
    directory = Path(catalog_dir or CATALOG_DIR)
    manifest = load_catalog_manifest(manifest_path)
    catalogs: dict[str, dict] = {}
    for language in manifest["languages"]:
        language_id = language["id"]
        catalog = _read_json(directory / f"{language_id}.json")
        _validate_catalog_shape(catalog, language, manifest["source_revision"])
        catalogs[language_id] = catalog

    english = catalogs["en"]
    message_keys = set(english["messages"])
    plural_keys = set(english["plurals"])
    all_keys = message_keys | plural_keys
    for flow in manifest["coverage_contract"]["localized_core_flows"]:
        for source in flow["sources"]:
            if not (ROOT / source).is_file():
                raise ValueError(f"localization core flow {flow['id']} source is missing: {source}")
        for prefix in flow["key_prefixes"]:
            if not any(key.startswith(prefix) for key in all_keys):
                raise ValueError(
                    f"localization core flow {flow['id']} has an empty key prefix: {prefix}"
                )
    for language in manifest["languages"]:
        language_id = language["id"]
        catalog = catalogs[language_id]
        if set(catalog["messages"]) != message_keys:
            raise ValueError(f"catalog {language_id} message keys do not match English")
        if set(catalog["plurals"]) != plural_keys:
            raise ValueError(f"catalog {language_id} plural keys do not match English")
        for key in message_keys:
            if _placeholders(catalog["messages"][key]) != _placeholders(english["messages"][key]):
                raise ValueError(f"catalog {language_id} message {key} has incorrect placeholders")
        for key in plural_keys:
            expected = _placeholders(english["plurals"][key]["other"])
            for category, value in catalog["plurals"][key].items():
                if _placeholders(value) != expected:
                    raise ValueError(
                        f"catalog {language_id} plural {key}.{category} has incorrect placeholders"
                    )

    return {
        "schema_version": 1,
        "source_revision": manifest["source_revision"],
        "message_count": len(message_keys),
        "plural_count": len(plural_keys),
        "coverage_contract": manifest["coverage_contract"],
        "languages": [
            {
                **language,
                "available": language["release_state"] == "available",
                "review_state": language["release_state"],
                "catalog_valid": True,
                "review": dict(catalogs[language["id"]]["review"]),
            }
            for language in manifest["languages"]
        ],
    }


def load_catalog(language: str, catalog_dir: Path | None = None) -> dict:
    status = validate_catalogs(catalog_dir=catalog_dir)
    normalized = str(language or "").strip().lower()
    metadata = next(
        (item for item in status["languages"] if item["id"].lower() == normalized), None
    )
    if metadata is None:
        raise ValueError("unknown interface language")
    directory = Path(catalog_dir or CATALOG_DIR)
    return _read_json(directory / f"{metadata['id']}.json")


def normalize_language(value: str) -> str:
    """Return the canonical ID for a known language that has passed every release gate."""

    normalized = str(value or "").strip().lower()
    item = next(
        (item for item in validate_catalogs()["languages"] if item["id"].lower() == normalized),
        None,
    )
    if not item or not item["available"]:
        raise ValueError("the selected language has not passed every release gate")
    return str(item["id"])


def localization_options() -> dict:
    status = validate_catalogs()
    return {
        "source_revision": status["source_revision"],
        "languages": [dict(item) for item in status["languages"]],
        "regions": [dict(item) for item in REGION_OPTIONS],
        "timezones": [dict(item) for item in TIMEZONE_OPTIONS],
        "currencies": [dict(item) for item in CURRENCY_OPTIONS],
        "clock_formats": [
            {"value": "auto", "label": "automatic"},
            {"value": "24", "label": "24 hour"},
            {"value": "12", "label": "12 hour"},
        ],
        "week_starts": [
            {"value": "auto", "label": "automatic"},
            {"value": "mon", "label": "monday"},
            {"value": "sun", "label": "sunday"},
        ],
    }
