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

# every iso 3166-1 region; the browser names them in the reader's language (Intl.DisplayNames),
# so the server only sends codes. seven hand-picked regions left out canada and most of the world
REGION_CODES = (
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS "
    "BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE "
    "EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM "
    "HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC "
    "LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA "
    "NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW "
    "SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO "
    "TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
).split()

REGION_OPTIONS = ({"value": "", "label": "automatic"},) + tuple(
    {"value": code, "label": code} for code in REGION_CODES
)

_ZONE_AREAS = (
    "Africa",
    "America",
    "Antarctica",
    "Asia",
    "Atlantic",
    "Australia",
    "Europe",
    "Indian",
    "Pacific",
)


def _timezone_options() -> tuple[dict, ...]:
    # the real tz database, not five picks; old aliases (US/Eastern, Etc/GMT+5) stay out
    from zoneinfo import available_timezones

    names = sorted(name for name in available_timezones() if name.split("/", 1)[0] in _ZONE_AREAS)
    return ({"value": "", "label": "automatic"}, {"value": "UTC", "label": "UTC"}) + tuple(
        {"value": name, "label": name} for name in names
    )


def _currency_options() -> tuple[dict, ...]:
    # every currency finance can hold, so the default currency is never missing one
    from services.finance_currency import SUPPORTED_CURRENCY_CODES

    return ({"value": "", "label": "automatic"},) + tuple(
        {"value": code, "label": code} for code in sorted(SUPPORTED_CURRENCY_CODES)
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
        "timezones": [dict(item) for item in _timezone_options()],
        "currencies": [dict(item) for item in _currency_options()],
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
