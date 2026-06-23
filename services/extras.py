"""5e - gated optional extras (native macOS bindings + heavy local-ML). this is the registry +
availability/gating only; the actual PhotoKit/EventKit/Keychain/CLIP/OCR implementations are
platform-specific + optional-dep and land when the host can run them. an extra is usable only when its
platform matches, its deps import, AND its opt-in setting is on.
"""

import importlib.util
import sys

# key -> {name, description, platforms (empty = any), requires (module names), setting}
EXTRAS = {
    "clip_search": {
        "name": "CLIP visual search",
        "description": "semantic image search over your photos (needs the clip/onnx model deps).",
        "platforms": (),
        "requires": ("onnxruntime",),
        "setting": "extra_clip_search",
    },
    "ocr": {
        "name": "OCR text extraction",
        "description": "pull text out of images/scans (needs an OCR engine).",
        "platforms": (),
        "requires": ("pytesseract",),
        "setting": "extra_ocr",
    },
    "photokit": {
        "name": "Apple Photos (PhotoKit)",
        "description": "import + sync from the macOS Photos library.",
        "platforms": ("darwin",),
        "requires": ("objc",),
        "setting": "extra_photokit",
    },
    "eventkit": {
        "name": "Apple Calendar (EventKit)",
        "description": "two-way sync with the macOS Calendar.",
        "platforms": ("darwin",),
        "requires": ("objc",),
        "setting": "extra_eventkit",
    },
    "keychain": {
        "name": "macOS Keychain",
        "description": "store secrets in the system Keychain instead of the app vault.",
        "platforms": ("darwin",),
        "requires": ("objc",),
        "setting": "extra_keychain",
    },
}


def _platform():
    return sys.platform


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def available(key):
    """can this extra actually run here? platform matches AND every required module imports."""
    spec = EXTRAS.get(key)
    if not spec:
        return False
    plats = spec.get("platforms") or ()
    if plats and _platform() not in plats:
        return False
    return all(_has_module(m) for m in spec.get("requires", ()))


def enabled(key, settings):
    """available AND the user has opted in via the setting."""
    spec = EXTRAS.get(key)
    if not spec or not available(key):
        return False
    return bool((settings or {}).get(spec["setting"], False))


def status(settings):
    """every extra with its availability/enabled state + a reason (for the settings UI)."""
    out = []
    for key, spec in EXTRAS.items():
        avail = available(key)
        plats = spec.get("platforms") or ()
        if not avail:
            if plats and _platform() not in plats:
                reason = f"needs {', '.join(plats)} (this host: {_platform()})"
            else:
                reason = f"missing deps: {', '.join(spec.get('requires', ())) or 'none'}"
        else:
            reason = "ready"
        out.append(
            {
                "key": key,
                "name": spec["name"],
                "description": spec["description"],
                "available": avail,
                "enabled": enabled(key, settings),
                "setting": spec["setting"],
                "reason": reason,
            }
        )
    return out
