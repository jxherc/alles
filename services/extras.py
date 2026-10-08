"""5e - gated optional extras (native macOS bindings + heavy local-ML).

This registry reports platform/dependency availability. Settings-gated extras
also require their opt-in flag; PhotoKit instead uses the explicit Gallery
import action and the macOS system permission prompt as its opt-in boundary.
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
        "description": "user-initiated import from the macOS Photos library.",
        "platforms": ("darwin",),
        "requires": (),
        "setting": None,  # clicking the Gallery action is the explicit opt-in
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
    if key == "photokit":
        try:
            from services import photokit

            return bool(photokit.status()["available"])
        except Exception:
            return False
    return all(_has_module(m) for m in spec.get("requires", ()))


def enabled(key, settings):
    """Available and, where configured, opted in through a setting."""
    spec = EXTRAS.get(key)
    if not spec or not available(key):
        return False
    setting = spec.get("setting")
    return available(key) if not setting else bool((settings or {}).get(setting, False))


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
                "setting": spec.get("setting"),
                "reason": reason,
            }
        )
    return out
