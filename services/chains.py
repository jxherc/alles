"""3c - composable tool chains: run a saved ordered list of capability invocations atomically,
templating each step's args from prior results with {{N}} / {{N.key}} refs. stops at the first error.
"""

import json
import re

_REF = re.compile(r"\{\{(\d+)(?:\.([a-zA-Z0-9_]+))?\}\}")


def _render(value, results):
    """substitute {{N}} (whole prior result) / {{N.key}} (a field of it) inside a string."""
    if not isinstance(value, str):
        return value

    def sub(m):
        idx = int(m.group(1))
        if idx >= len(results):
            return m.group(0)  # no such step yet -> leave the ref intact
        res = results[idx]
        key = m.group(2)
        if key is None:
            return res if isinstance(res, str) else json.dumps(res)
        if isinstance(res, dict) and key in res:
            v = res[key]
            return v if isinstance(v, str) else json.dumps(v)
        return m.group(0)

    return _REF.sub(sub, value)


def _render_args(args, results):
    return {k: _render(v, results) for k, v in (args or {}).items()}


async def run_chain(steps, *, invoke, ctx=None):
    """run each step through `invoke(name, args, kind)`. returns {results, ok}. on the first error
    the chain stops and the failing step's result holds an `error`."""
    results = []
    for step in steps or []:
        name = step.get("name", "")
        kind = step.get("kind", "tool")
        args = _render_args(step.get("args", {}), results)
        try:
            res = await invoke(name, args, kind)
            results.append(res if res is not None else {})
        except Exception as e:
            results.append({"error": f"{type(e).__name__}: {e}", "step": name})
            return {"results": results, "ok": False}
    return {"results": results, "ok": True}
