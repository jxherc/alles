"""Deterministic, source-derived literal control census for Alles.

The census records only bounded source facts.  It classifies each activation
without turning a source reference into a claim that the browser exercised it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from services.feature_registry import load_registry, ownership_map

ROOT = Path(__file__).parents[1]
INDEX_PATH = ROOT / "static" / "index.html"
JS_DIR = ROOT / "static" / "js"
TESTS_DIR = ROOT / "tests"
OVERRIDES_PATH = ROOT / "features" / "control-census-overrides.json"
CONTRACTS_PATH = ROOT / "design-system" / "components" / "contracts.json"

VISUAL_STATES = (
    "resting",
    "hover",
    "pressed",
    "selected",
    "disabled",
    "busy",
    "invalid",
    "loading",
    "empty",
    "permission",
    "offline",
    "stale",
    "partial",
    "error",
)
INTERACTIVE_TAGS = {"button", "input", "textarea", "select", "summary"}
INTERACTIVE_ROLES = {
    "button",
    "checkbox",
    "link",
    "menuitem",
    "menuitemradio",
    "option",
    "radio",
    "switch",
    "tab",
}
CONTROL_TAG_RE = re.compile(
    r"<(button|a|input|textarea|select|summary)\b(?P<attrs>[^>]*?)>", re.I | re.S
)
ROLE_TAG_RE = re.compile(
    r"<(?P<tag>[a-z][\w-]*)\b(?P<attrs>[^>]*?\brole\s*=\s*['\"](?:button|checkbox|link|menuitem|menuitemradio|option|radio|switch|tab)['\"][^>]*?)>",
    re.I | re.S,
)
INLINE_ACTION_TAG_RE = re.compile(
    r"<(?P<tag>[a-z][\w-]*)\b(?P<attrs>[^>]*?\bon(?:click|contextmenu|dblclick)\s*=\s*[^>]+?)>",
    re.I | re.S,
)
CREATE_RE = re.compile(r"createElement\(\s*['\"](?P<tag>button|a|input|textarea|select)['\"]\s*\)")
EVENT_RE = re.compile(r"addEventListener\(\s*['\"](?P<event>[A-Za-z]+)['\"]")
FUNCTION_RE = re.compile(
    r"(?m)^(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\(|^(?:export\s+)?(?:const|let|var)\s+(?P<assigned>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^\n]*?\)|[A-Za-z_$][\w$]*)\s*=>"
)
FETCH_RE = re.compile(r"fetch\(\s*(?:`|['\"])(?P<path>/api/[^`'\"?${]+)")
ID_LISTENER_RE = re.compile(
    r"(?:document\.)?getElementById\(\s*['\"](?P<id>[^'\"]+)['\"]\s*\)\?*\.addEventListener\(\s*['\"](?P<event>[A-Za-z]+)['\"]"
    r"|\$\(\s*['\"](?P<dollar_id>[^'\"]+)['\"]\s*\)\?*\.addEventListener\(\s*['\"](?P<dollar_event>[A-Za-z]+)['\"]"
)
ID_ASSIGNMENT_RE = re.compile(
    r"(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:document\.)?getElementById\(\s*['\"](?P<id>[^'\"]+)['\"]\s*\)"
)
ATTR_RE = re.compile(r"([:\w-]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>`]+)))?")


class ControlCensusError(ValueError):
    """The control census inputs or generated document are malformed."""


def _attrs(raw: str) -> dict[str, str]:
    return {
        match.group(1).lower(): next(
            (value for value in match.groups()[1:] if value is not None), ""
        )
        for match in ATTR_RE.finditer(raw)
    }


def _kind(tag: str, attrs: dict[str, str]) -> str:
    role = attrs.get("role", "")
    if role == "tab":
        return "tab"
    if role in {"menuitem", "menuitemradio"}:
        return "menu-item"
    if role in {"radio", "option"}:
        return "choice"
    if role in {"switch", "checkbox"}:
        return "switch"
    if tag == "a":
        return "link"
    if tag in {"input", "textarea", "select"}:
        return "field"
    if attrs.get("type") == "submit":
        return "form-submit"
    if "icon-btn" in attrs.get("class", "").split():
        return "icon-action"
    return "action"


def _modalities(tag: str, attrs: dict[str, str]) -> list[dict[str, Any]]:
    modalities: list[dict[str, Any]] = []
    if tag == "a" and attrs.get("href"):
        modalities.append(
            {"modality": "pointer", "event": "click", "keys": ["Enter"], "preconditions": []}
        )
    elif tag in {"button", "summary"} or attrs.get("role") in INTERACTIVE_ROLES:
        modalities.extend(
            [
                {"modality": "pointer", "event": "click", "keys": [], "preconditions": []},
                {
                    "modality": "keyboard",
                    "event": "activation",
                    "keys": ["Enter", "Space"],
                    "preconditions": [],
                },
            ]
        )
    elif tag in {"input", "textarea", "select"}:
        modalities.append(
            {
                "modality": "keyboard",
                "event": "native-edit",
                "keys": ["native editing keys"],
                "preconditions": [],
            }
        )
    for attr, modality, event, keys in (
        ("oncontextmenu", "context", "contextmenu", ["ContextMenu", "Shift+F10"]),
        ("ondblclick", "pointer", "dblclick", []),
    ):
        if attrs.get(attr):
            modalities.append(
                {"modality": modality, "event": event, "keys": keys, "preconditions": []}
            )
    return modalities


def _with_direct_listener_paths(
    variants: list[dict[str, Any]], listeners: list[str]
) -> list[dict[str, Any]]:
    """Add non-native direct-id listeners without pretending to know their keys."""
    known_events = {variant["event"] for variant in variants}
    event_shapes = {
        "keydown": ("keyboard", ["handler-defined keys require source inspection"]),
        "keyup": ("keyboard", ["handler-defined keys require source inspection"]),
        "contextmenu": ("context", ["ContextMenu", "Shift+F10"]),
        "dblclick": ("pointer", []),
        "pointerdown": ("gesture", []),
        "pointermove": ("gesture", []),
        "pointerup": ("gesture", []),
        "dragstart": ("gesture", []),
        "dragover": ("gesture", []),
        "drop": ("gesture", []),
        "submit": ("keyboard", ["Enter or an explicit submit control"]),
        "change": ("keyboard", ["value selection keys or pointer"]),
        "input": ("keyboard", ["native editing keys"]),
    }
    for listener in listeners:
        event = listener.rsplit(" ", 1)[-1]
        if event in known_events or event not in event_shapes:
            continue
        modality, keys = event_shapes[event]
        variants.append({"modality": modality, "event": event, "keys": keys, "preconditions": []})
        known_events.add(event)
    return variants


@lru_cache(maxsize=None)
def _test_reference_index() -> dict[str, tuple[dict[str, Any], ...]]:
    """Index literal test tokens once; census generation must not scan tests per control."""
    indexed: dict[str, list[dict[str, Any]]] = {}
    token_re = re.compile(r"(?<![\w-])([A-Za-z][\w-]{2,})(?![\w-])")
    for path in sorted(TESTS_DIR.rglob("*")):
        if path.suffix not in {".py", ".mjs", ".js"}:
            continue
        relative = path.relative_to(ROOT).as_posix()
        for line_number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            for token in set(token_re.findall(line)):
                indexed.setdefault(token, []).append(
                    {
                        "file": relative,
                        "line": line_number,
                        "kind": "existing-test-control-reference",
                        "claim": "control is named; activation path is not mechanically classified",
                    }
                )
    return {token: tuple(references) for token, references in indexed.items()}


def _test_references(control_anchor: str | None) -> tuple[dict[str, Any], ...]:
    """Return exact, conservative test mentions for a stable DOM anchor.

    A mention proves only that an existing test names the control.  It does not
    prove a particular activation path: many tests bind a locator on one line
    and activate it on a later line.  Keeping that distinction in the data is
    important for the literal census - it prevents a selector assertion from
    being reported as pointer or keyboard proof.
    """
    if not control_anchor:
        return ()
    return _test_reference_index().get(control_anchor, ())


def _path_statement(
    variant: dict[str, Any],
    handler: dict[str, Any],
    *,
    tag: str,
    attrs: dict[str, str],
    external: bool,
) -> tuple[str, str]:
    """Return a bounded source classification, never an inferred runtime result."""
    if external:
        return (
            "external-navigation - browser hands the declared destination to an external authority",
            "external-navigation - no application state transition is asserted",
        )
    authority = handler["classification"]
    if authority == "native-link-navigation":
        return (
            "native-link-navigation - browser follows the declared local href",
            "document-navigation - the browser changes the current document or fragment",
        )
    if authority == "native-field-edit":
        return (
            "native-field-edit - browser accepts a value edit through the native form control",
            "native-control-value - the control value can change before any source listener runs",
        )
    if authority == "native-form-submission":
        return (
            "native-form-submission - browser submits through the enclosing form when present",
            "form-submission-dispatch - application state is not asserted by this source record",
        )
    if authority in {"inline-handler", "direct-id-listener", "nearest-enclosing-controller"}:
        return (
            f"source-authority-dispatch - activation invokes the matched {authority}",
            "source-authority-owned-transition - any post-handler state change requires runtime evidence",
        )
    return (
        "semantic-activation-without-matched-authority - source declares an activatable control but no direct or delegated authority was located",
        "no-source-transition-declared - static extraction makes no state-change claim",
    )


def _activation_paths(
    variants: list[dict[str, Any]],
    *,
    source: dict[str, Any],
    control_anchor: str | None,
    handler: dict[str, Any],
    tag: str,
    attrs: dict[str, str],
    external: bool,
) -> list[dict[str, Any]]:
    """Attach source and test provenance to each source-discoverable path."""
    tests = list(_test_references(control_anchor))
    source_ref = {"file": source["file"], "line": source["line"], "kind": "control-source"}
    paths: list[dict[str, Any]] = []
    for variant in variants:
        outcome, transition = _path_statement(
            variant, handler, tag=tag, attrs=attrs, external=external
        )
        status = (
            "external-blocked"
            if external
            else "test-linked-unclassified"
            if tests
            else "source-only"
        )
        paths.append(
            {
                **variant,
                "handler_provenance": handler,
                "outcome": outcome,
                "state_transition": transition,
                "evidence": {
                    "status": status,
                    "source": source_ref,
                    "tests": tests,
                },
            }
        )
    return paths


def _native_handler(
    tag: str, attrs: dict[str, str], direct_handlers: list[str], inline_handler: str | None
) -> dict[str, str]:
    """Classify the closest authority that source extraction can name."""
    if inline_handler:
        return {
            "value": inline_handler,
            "discoverability": "inline",
            "classification": "inline-handler",
        }
    if direct_handlers:
        return {
            "value": "; ".join(direct_handlers),
            "discoverability": "direct-id-listener",
            "classification": "direct-id-listener",
        }
    href = attrs.get("href", "")
    if tag == "a" and href and not href.startswith(("http://", "https://", "mailto:")):
        return {
            "value": f"declared href={href}",
            "discoverability": "native-declaration",
            "classification": "native-link-navigation",
        }
    if tag in {"input", "textarea", "select"}:
        return {
            "value": f"native {tag} editing",
            "discoverability": "native-declaration",
            "classification": "native-field-edit",
        }
    if attrs.get("type") == "submit":
        return {
            "value": "native submit control",
            "discoverability": "native-declaration",
            "classification": "native-form-submission",
        }
    return {
        "value": "no direct-id listener, inline handler, or native authority matched by static source extraction",
        "discoverability": "no-matched-source-authority",
        "classification": "no-matched-source-authority",
    }


def _recovery(
    handler: dict[str, str], *, tag: str, attrs: dict[str, str], external: bool, destructive: bool
) -> dict[str, Any]:
    """State why recovery is native, outside the app, or absent from matched source."""
    if external:
        return {
            "classification": "not-applicable",
            "value": "not-applicable - destination handling belongs to the external authority",
            "reason": "the application does not own the external destination",
            "controls": [],
        }
    if handler["classification"] == "native-field-edit":
        return {
            "classification": "native-browser-undo",
            "value": "native-browser-undo - browser editing recovery is user-agent behavior",
            "reason": "no application recovery controller is declared for the native edit",
            "controls": [],
        }
    if handler["classification"] == "native-link-navigation":
        return {
            "classification": "not-applicable",
            "value": "not-applicable - navigation recovery is browser history behavior",
            "reason": "the source record declares navigation rather than an application mutation",
            "controls": [],
        }
    if destructive:
        return {
            "classification": "source-recovery-not-declared",
            "value": "source-recovery-not-declared - no restore or undo control was located for the matched authority",
            "reason": "static source extraction found no recovery declaration",
            "controls": [],
        }
    return {
        "classification": "not-applicable",
        "value": "not-applicable - this record has no source-declared destructive mutation to recover",
        "reason": "the census does not infer a mutation from a control alone",
        "controls": [],
    }


def _inline_handler(attrs: dict[str, str]) -> str | None:
    values = [
        f"{key}={attrs[key]}"
        for key in ("onclick", "oncontextmenu", "ondblclick")
        if attrs.get(key)
    ]
    return "; ".join(values) or None


def _label(attrs: dict[str, str], text: str) -> tuple[str | None, str]:
    for key in ("aria-label", "title", "value", "placeholder", "name", "id"):
        if attrs.get(key):
            return attrs[key].strip(), key
    compact = " ".join(text.split())
    return (compact, "text") if compact else (None, "unknown")


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:12]


class _StaticControls(HTMLParser):
    def __init__(
        self,
        owners: dict[str, str],
        handler_hints: dict[str, list[str]],
        control_overrides: dict[str, str],
    ):
        super().__init__(convert_charrefs=True)
        self.owners = owners
        self.handler_hints = handler_hints
        self.control_overrides = control_overrides
        self.stack: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []
        self.anchor_occurrences: Counter[str] = Counter()

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key.lower(): value or "" for key, value in attrs_list}
        inherited = self.stack[-1]["owner"] if self.stack else None
        owner = self.owners.get("body") if tag == "body" else inherited
        if attrs.get("id") and f"#{attrs['id']}" in self.owners:
            owner = self.owners[f"#{attrs['id']}"]
        line, column = self.getpos()
        interactive = (
            tag in INTERACTIVE_TAGS
            or attrs.get("role") in INTERACTIVE_ROLES
            or attrs.get("contenteditable") in {"", "true"}
            or attrs.get("tabindex", "").lstrip("-").isdigit()
            or (tag == "a" and attrs.get("href"))
            or "data-action" in attrs
            or "onclick" in attrs
            or "oncontextmenu" in attrs
            or "ondblclick" in attrs
            or "s-switch" in attrs.get("class", "").split()
            or "s-nav-item" in attrs.get("class", "").split()
        )
        node = {
            "tag": tag,
            "attrs": attrs,
            "owner": owner,
            "text": [],
            "line": line,
            "column": column,
            "interactive": interactive,
        }
        self.stack.append(node)
        if tag in {"input", "select"} and interactive:
            self._record(node, "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        for node in self.stack:
            node["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            node = self.stack[index]
            if node["interactive"] and tag not in {"input", "select"}:
                self._record(node, "".join(node["text"]))
            del self.stack[index:]
            return

    def _record(self, node: dict[str, Any], text: str) -> None:
        attrs = node["attrs"]
        label, label_source = _label(attrs, text)
        source = f"static/index.html:{node['line']}:{node['column']}"
        identity_attrs = "|".join(
            f"{key}={value}"
            for key, value in sorted(attrs.items())
            if key not in {"style", "hidden"}
        )
        stable_anchor = (
            attrs.get("id")
            or attrs.get("data-action")
            or attrs.get("data-testid")
            or f"{node['tag']}:{identity_attrs}:{label or ''}"
        )
        self.anchor_occurrences[stable_anchor] += 1
        control_id = f"static.{_fingerprint(node['tag'], stable_anchor, str(self.anchor_occurrences[stable_anchor]))}"
        owner = self.control_overrides.get(attrs.get("id", ""), node["owner"])
        flags = []
        if not attrs.get("id") and not attrs.get("data-testid"):
            flags.append("anonymous-source-anchor")
        if not owner:
            flags.append("orphan-feature-owner")
        if isinstance(owner, str) and owner.startswith("cross-feature."):
            flags.append("cross-feature-owner")
        if label is None:
            flags.append("unknown-label")
        if attrs.get("onclick"):
            flags.append("inline-handler")
        inline_handler = _inline_handler(attrs)
        direct_handlers = self.handler_hints.get(attrs.get("id", ""), [])
        trigger_variants = _with_direct_listener_paths(
            _modalities(node["tag"], attrs), direct_handlers
        )
        handler = _native_handler(node["tag"], attrs, direct_handlers, inline_handler)
        external = bool(
            node["tag"] == "a" and attrs.get("href", "").startswith(("http://", "https://"))
        )
        destructive = _destructive(attrs, label)
        self.controls.append(
            {
                "id": control_id,
                "feature_owner": owner or "unmapped-static-owner",
                "surface": {
                    "root": _owning_root(attrs, owner, self.owners),
                    "render_mode": "static",
                    "source": {
                        "file": "static/index.html",
                        "line": node["line"],
                        "column": node["column"],
                    },
                    "source_selector": source,
                    "runtime_selector": f"#{attrs['id']}" if attrs.get("id") else None,
                    "instance_key": None,
                    "visibility_condition": "source-visible unless an existing hidden/conditional attribute or ancestor state applies",
                },
                "kind": _kind(node["tag"], attrs),
                "label": {"value": label, "source": label_source},
                "trigger_variants": trigger_variants,
                "activation_paths": _activation_paths(
                    trigger_variants,
                    source={"file": "static/index.html", "line": node["line"]},
                    control_anchor=attrs.get("id"),
                    handler=handler,
                    tag=node["tag"],
                    attrs=attrs,
                    external=external,
                ),
                "handler": handler,
                "authority": {
                    "classification": handler["classification"],
                    "guards": [],
                    "confirmation": "not-declared-in-control-source",
                    "busy_repeat": "shared-contract-or-not-declared-in-control-source",
                },
                "path": {
                    "client_functions": [],
                    "api": [],
                    "server_owner": "not-declared-in-control-source",
                    "external_destination": attrs.get("href") if node["tag"] == "a" else None,
                },
                "effect": {
                    "value": "source-effect-not-declared",
                    "reversible": "not-declared-in-control-source",
                    "destructive": destructive,
                    "external": external,
                },
                "states": {
                    "visual": list(VISUAL_STATES),
                    "outcome_status": ["source-classified-not-runtime-proven"],
                    "conditional_states": [],
                },
                "accessibility": {
                    "role": attrs.get("role") or ("native " + node["tag"]),
                    "name": label,
                    "relationships": {
                        key: attrs[key]
                        for key in (
                            "aria-controls",
                            "aria-expanded",
                            "aria-pressed",
                            "aria-checked",
                            "aria-current",
                            "aria-haspopup",
                        )
                        if key in attrs
                    },
                    "focus": "native or shared KOKUEN focus treatment; exact runtime proof pending",
                },
                "recovery": _recovery(
                    handler,
                    tag=node["tag"],
                    attrs=attrs,
                    external=external,
                    destructive=destructive,
                ),
                "evidence": {
                    "status": "not-applicable"
                    if node["tag"] == "a" and attrs.get("href", "").startswith("mailto:")
                    else "programmatic-dom",
                    "references": [],
                },
                "flags": flags,
            }
        )


def _owning_root(attrs: dict[str, str], owner: str | None, owners: dict[str, str]) -> str | None:
    if attrs.get("id") and f"#{attrs['id']}" in owners:
        return f"#{attrs['id']}"
    for selector, feature in owners.items():
        if feature == owner:
            return selector
    return None


def _destructive(attrs: dict[str, str], label: str | None) -> bool:
    text = " ".join([attrs.get("class", ""), attrs.get("title", ""), label or ""]).lower()
    return any(
        word in text
        for word in ("delete", "remove", "revoke", "trash", "destroy", "discard", "cancel")
    )


def _dynamic_templates(overrides: dict[str, Any]) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for path in sorted(JS_DIR.glob("*.js")):
        text = path.read_text("utf-8")
        relative = path.relative_to(ROOT).as_posix()
        owner = overrides.get("module_feature_hints", {}).get(relative, "unmapped-module-owner")
        matches: list[tuple[int, str, dict[str, str], str]] = []
        for pattern in (CONTROL_TAG_RE, ROLE_TAG_RE, INLINE_ACTION_TAG_RE):
            for match in pattern.finditer(text):
                tag = match.groupdict().get("tag") or match.group(1)
                matches.append(
                    (match.start(), tag.lower(), _attrs(match.group("attrs")), "markup-template")
                )
        for match in CREATE_RE.finditer(text):
            matches.append((match.start(), match.group("tag").lower(), {}, "create-element"))
        seen: set[tuple[int, str]] = set()
        anchor_occurrences: Counter[str] = Counter()
        for ordinal, (offset, tag, attrs, construction) in enumerate(sorted(matches), start=1):
            if (offset, tag) in seen:
                continue
            seen.add((offset, tag))
            line = text.count("\n", 0, offset) + 1
            label, label_source = _label(attrs, _template_text(text, offset, tag))
            # Dynamic renderers can legitimately repeat one DOM id in mutually
            # exclusive dialog templates. The census identity is the source
            # template, never the prospective runtime DOM id.
            semantic_anchor = (
                attrs.get("id")
                or attrs.get("data-action")
                or f"{tag}:{'|'.join(f'{key}={value}' for key, value in sorted(attrs.items()) if key != 'style')}:{label or ''}"
            )
            anchor_occurrences[semantic_anchor] += 1
            anchor = f"{semantic_anchor}:{anchor_occurrences[semantic_anchor]}"
            context = _source_context(text, offset, relative)
            flags = ["dynamic-template"]
            if owner == "unmapped-module-owner":
                flags.append("orphan-feature-owner")
            if owner.startswith("cross-feature."):
                flags.append("cross-feature-owner")
            if label is None:
                flags.append("unknown-label")
            trigger_variants = _modalities(tag, attrs)
            inline_handler = _inline_handler(attrs)
            if inline_handler:
                handler = {
                    "value": inline_handler,
                    "discoverability": "inline",
                    "classification": "inline-handler",
                }
            elif context["handler"]:
                handler = {
                    "value": context["handler"],
                    "discoverability": "nearest-enclosing-function",
                    "classification": "nearest-enclosing-controller",
                }
            else:
                handler = _native_handler(tag, attrs, [], None)
            external = bool(
                tag == "a" and attrs.get("href", "").startswith(("http://", "https://"))
            )
            destructive = _destructive(attrs, label)
            templates.append(
                {
                    "id": f"dynamic.{_fingerprint(relative, anchor, tag)}",
                    "feature_owner": owner,
                    "surface": {
                        "root": None,
                        "render_mode": "dynamic-template",
                        "source": {"file": relative, "line": line, "column": None},
                        "source_selector": f"{relative}:{line}:{ordinal}",
                        "runtime_selector": f"#{attrs['id']}" if attrs.get("id") else None,
                        "instance_key": _instance_key(attrs),
                        "visibility_condition": "runtime renderer condition unknown; inspect the source template and rendered DOM",
                    },
                    "kind": _kind(tag, attrs),
                    "label": {"value": label, "source": label_source},
                    "trigger_variants": trigger_variants,
                    "activation_paths": _activation_paths(
                        trigger_variants,
                        source={"file": relative, "line": line},
                        control_anchor=attrs.get("id"),
                        handler=handler,
                        tag=tag,
                        attrs=attrs,
                        external=external,
                    ),
                    "handler": handler,
                    "authority": {
                        "classification": handler["classification"],
                        "guards": [],
                        "confirmation": "not-declared-in-template-source",
                        "busy_repeat": "not-declared-in-template-source",
                    },
                    "path": {
                        "client_functions": [context["handler"]] if context["handler"] else [],
                        "api": context["api"],
                        "server_owner": "not-declared-in-template-source",
                        "external_destination": attrs.get("href") if tag == "a" else None,
                    },
                    "effect": {
                        "value": "source-effect-not-declared",
                        "reversible": "not-declared-in-template-source",
                        "destructive": destructive,
                        "external": external,
                    },
                    "states": {
                        "visual": list(VISUAL_STATES),
                        "outcome_status": ["source-classified-not-runtime-proven"],
                        "conditional_states": [],
                    },
                    "accessibility": {
                        "role": attrs.get("role") or ("native " + tag),
                        "name": label,
                        "relationships": {
                            key: attrs[key]
                            for key in (
                                "aria-controls",
                                "aria-expanded",
                                "aria-pressed",
                                "aria-checked",
                                "aria-current",
                                "aria-haspopup",
                            )
                            if key in attrs
                        },
                        "focus": "unknown until runtime evidence is attached",
                    },
                    "recovery": _recovery(
                        handler, tag=tag, attrs=attrs, external=external, destructive=destructive
                    ),
                    "evidence": {"status": "programmatic-dom", "references": []},
                    "flags": flags
                    + (
                        ["anonymous-source-anchor"]
                        if not attrs.get("id") and not attrs.get("data-action")
                        else []
                    )
                    + (["inline-handler"] if inline_handler else []),
                    "construction": construction,
                }
            )
    return templates


def _instance_key(attrs: dict[str, str]) -> str:
    for key in attrs:
        if key.startswith("data-") and key not in {"data-action"}:
            return f"runtime record value from {key}"
    return "source-template may render zero to many instances"


def _template_text(source: str, offset: int, tag: str) -> str:
    start = source.find(">", offset)
    if start < 0:
        return ""
    end = source.find(f"</{tag}>", start + 1)
    if end < 0 or end - start > 300:
        return ""
    return re.sub(r"<[^>]+>", " ", source[start + 1 : end])


def _source_context(source: str, offset: int, relative: str) -> dict[str, Any]:
    candidates = list(FUNCTION_RE.finditer(source, 0, offset + 1))
    if not candidates:
        return {"handler": None, "api": [], "events": []}
    match = candidates[-1]
    name = match.group("name") or match.group("assigned")
    following = FUNCTION_RE.search(source, match.end())
    block = source[match.start() : following.start() if following else len(source)]
    line = source.count("\n", 0, match.start()) + 1
    return {
        "handler": f"{relative}:{line} {name}",
        "api": sorted(
            set(f"source-local:{item.group('path')}" for item in FETCH_RE.finditer(block))
        ),
        "events": sorted(set(item.group("event") for item in EVENT_RE.finditer(block))),
    }


def _direct_id_listener_hints() -> dict[str, list[str]]:
    hints: dict[str, list[str]] = {}
    for path in sorted(JS_DIR.glob("*.js")):
        text = path.read_text("utf-8")
        relative = path.relative_to(ROOT).as_posix()
        for match in ID_LISTENER_RE.finditer(text):
            control_id = match.group("id") or match.group("dollar_id")
            event = match.group("event") or match.group("dollar_event")
            line = text.count("\n", 0, match.start()) + 1
            hints.setdefault(control_id, []).append(f"{relative}:{line} {event}")
        # Shell wiring often resolves a control once, then registers the event
        # on that local variable. This remains direct source authority and is
        # more precise than treating the static control as unbound.
        assignments = list(ID_ASSIGNMENT_RE.finditer(text))
        for index, assignment in enumerate(assignments):
            name = assignment.group("name")
            control_id = assignment.group("id")
            # The same local name is commonly reused by separate renderer
            # functions. Limit this authority search to its next assignment,
            # rather than letting a later `trigger` shadow an earlier one.
            end = next(
                (
                    candidate.start()
                    for candidate in assignments[index + 1 :]
                    if candidate.group("name") == name
                ),
                len(text),
            )
            listener_re = re.compile(
                rf"\b{re.escape(name)}\?*\.addEventListener\(\s*['\"](?P<event>[A-Za-z]+)['\"]"
            )
            for match in listener_re.finditer(text, assignment.end(), end):
                line = text.count("\n", 0, match.start()) + 1
                hint = f"{relative}:{line} {match.group('event')}"
                if hint not in hints.setdefault(control_id, []):
                    hints[control_id].append(hint)
    return hints


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlCensusError(f"cannot load census overrides: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 3:
        raise ControlCensusError("control census overrides schema_version must be 3")
    if not isinstance(value.get("module_feature_hints"), dict) or not isinstance(
        value.get("controls"), dict
    ):
        raise ControlCensusError(
            "control census overrides need module_feature_hints and controls objects"
        )
    return value


def resolved_control_census() -> dict[str, Any]:
    registry = load_registry()
    owners = ownership_map(registry, "control_roots")
    overrides = load_overrides()
    parser = _StaticControls(owners, _direct_id_listener_hints(), overrides["controls"])
    parser.feed(INDEX_PATH.read_text("utf-8"))
    controls = parser.controls + _dynamic_templates(overrides)
    ids = [row["id"] for row in controls]
    if len(ids) != len(set(ids)):
        raise ControlCensusError("control census generated duplicate ids")
    try:
        vocabulary = json.loads(CONTRACTS_PATH.read_text("utf-8"))["state_vocabulary"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ControlCensusError(f"cannot load KOKUEN state vocabulary: {exc}") from exc
    if vocabulary != list(VISUAL_STATES):
        raise ControlCensusError("control census state vocabulary drifted from KOKUEN contracts")
    events = Counter()
    for path in sorted(JS_DIR.glob("*.js")):
        events.update(match.group("event") for match in EVENT_RE.finditer(path.read_text("utf-8")))
    paths = [path for row in controls for path in row["activation_paths"]]
    path_evidence = Counter(path["evidence"]["status"] for path in paths)
    return {
        "schema_version": 3,
        "title": "Alles literal control census",
        "generated_from": [
            "features/registry.json",
            "features/control-census-overrides.json",
            "static/index.html",
            "static/js/*.js",
        ],
        "visual_state_vocabulary": list(VISUAL_STATES),
        "evidence_levels": [
            "pointer-real",
            "keyboard-real",
            "simulated-route",
            "programmatic-dom",
            "backend-only",
            "external-blocked",
            "not-applicable",
        ],
        "summary": {
            "static_controls": len(parser.controls),
            "dynamic_templates": len(controls) - len(parser.controls),
            "controls": len(controls),
            "activation_paths": len(paths),
            "activation_path_evidence": dict(sorted(path_evidence.items())),
            "event_listener_types": dict(sorted(events.items())),
            "flags": dict(
                sorted(Counter(flag for row in controls for flag in row["flags"]).items())
            ),
        },
        "controls": controls,
    }
