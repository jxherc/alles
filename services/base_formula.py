"""4d - Base computed/formula fields: a safe evaluator for expressions like "{price} * {qty}" or
"'shipped' if {done} else 'open'". {field} refs resolve from a row dict.

security: parses a restricted Python AST and walks only a whitelist of node types + functions. no
attribute access, no calls to non-whitelisted names, no imports/comprehensions - safe on user input.
"""

import ast
import operator
import re

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_FUNCS = {
    "round": round,
    "abs": abs,
    "min": min,
    "max": max,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "upper": lambda s: str(s).upper(),
    "lower": lambda s: str(s).lower(),
}

_FIELD = re.compile(r"\{([a-zA-Z0-9_ ]+)\}")


def _coerce(v):
    """numbers stored as strings still do arithmetic; leave real strings alone."""
    if isinstance(v, str):
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except ValueError:
            return v
    return v


def _resolve_fields(formula, row):
    """replace {field} with a placeholder identifier and build the eval namespace."""
    ns = {}
    counter = [0]

    def sub(m):
        key = m.group(1).strip()
        name = f"_f{counter[0]}"
        counter[0] += 1
        val = row.get(key, 0)  # missing -> 0 so numeric formulas still compute
        ns[name] = _coerce(val)
        return name

    return _FIELD.sub(sub, formula), ns


def _ev(node, ns):
    if isinstance(node, ast.Expression):
        return _ev(node.body, ns)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in ns:
            return ns[node.id]
        raise ValueError(f"unknown name: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_ev(node.left, ns), _ev(node.right, ns))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
        v = _ev(node.operand, ns)
        return (
            -v if isinstance(node.op, ast.USub) else (not v if isinstance(node.op, ast.Not) else +v)
        )
    if isinstance(node, ast.BoolOp):
        vals = [_ev(v, ns) for v in node.values]
        if isinstance(node.op, ast.And):
            out = True
            for v in vals:
                out = v
                if not v:
                    break
            return out
        out = False
        for v in vals:
            out = v
            if v:
                break
        return out
    if isinstance(node, ast.Compare):
        left = _ev(node.left, ns)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMP:
                raise ValueError("bad comparison")
            right = _ev(comp, ns)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _ev(node.body, ns) if _ev(node.test, ns) else _ev(node.orelse, ns)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("function not allowed")
        args = [_ev(a, ns) for a in node.args]
        return _FUNCS[node.func.id](*args)
    raise ValueError(f"unsupported expression: {type(node).__name__}")


def evaluate(formula, row):
    """compute a formula against a row dict. returns the value, or {'error': msg} on anything bad."""
    try:
        expr, ns = _resolve_fields(formula or "", row or {})
        tree = ast.parse(expr, mode="eval")
        return _ev(tree, ns)
    except ZeroDivisionError:
        return {"error": "division by zero"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
