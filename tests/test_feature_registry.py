import ast
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.routing import APIRoute

from app import app
from services import automations, capabilities
from services.feature_registry import load_registry, ownership_map


ROOT = Path(__file__).parents[1]


def _walk_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk_routes(route.original_router.routes)


def _literal_registry_call_names(path: Path, owner: str, method: str) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == method
            and isinstance(func.value, ast.Name)
            and func.value.id == owner
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
    return names


def _cli_commands(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "COMMANDS" for target in node.targets):
            if not isinstance(node.value, ast.Dict):
                break
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("cli.py COMMANDS literal is missing")


class _ControlInventory(HTMLParser):
    INTERACTIVE_TAGS = {"button", "input", "select", "textarea", "summary"}
    INTERACTIVE_ROLES = {"button", "checkbox", "link", "menuitem", "option", "radio", "switch", "tab"}

    def __init__(self, roots: dict[str, str]):
        super().__init__(convert_charrefs=True)
        self.roots = roots
        self.stack = []
        self.controls = []
        self.seen_roots = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        parent_owner = self.stack[-1][1] if self.stack else None
        selectors = (["body"] if tag == "body" else []) + ([f"#{values['id']}"] if values.get("id") else [])
        owner = parent_owner
        for selector in selectors:
            if selector in self.roots:
                owner = self.roots[selector]
                self.seen_roots.add(selector)
        self.stack.append((tag, owner))
        classes = set(values.get("class", "").split())
        interactive = (
            tag in self.INTERACTIVE_TAGS
            or values.get("role") in self.INTERACTIVE_ROLES
            or values.get("contenteditable") in {"", "true"}
            or values.get("tabindex", "").lstrip("-").isdigit()
            or "s-switch" in classes
            or "s-nav-item" in classes
            or values.get("data-action") is not None
        )
        if tag == "a" and values.get("href"):
            interactive = True
        if interactive:
            self.controls.append((tag, values.get("id", ""), owner))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


class FeatureRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_every_runtime_route_owner_maps_to_one_feature(self):
        runtime = {route.endpoint.__module__ for route in _walk_routes(app.routes)}
        mapped = set(ownership_map(self.registry, "route_modules"))
        self.assertEqual(runtime, mapped, {"unmapped": sorted(runtime - mapped), "stale": sorted(mapped - runtime)})

    def test_every_cli_command_job_action_and_aide_tool_maps_to_one_feature(self):
        runtime_cli = _cli_commands(ROOT / "cli.py")
        runtime_jobs = _literal_registry_call_names(ROOT / "app.py", "jobs", "register")
        capabilities.clear()
        capabilities.bootstrap()
        runtime_tools = {row.name for row in capabilities.all(kind="tool")}
        runtime_actions = set(automations.ACTIONS)
        expected = {
            "cli_commands": runtime_cli,
            "jobs": runtime_jobs,
            "automation_actions": runtime_actions,
            "aide_tools": runtime_tools,
        }
        for surface, runtime in expected.items():
            with self.subTest(surface=surface):
                mapped = set(ownership_map(self.registry, surface))
                self.assertEqual(runtime, mapped, {"unmapped": sorted(runtime - mapped), "stale": sorted(mapped - runtime)})

    def test_every_interactive_source_control_has_a_feature_owner(self):
        roots = ownership_map(self.registry, "control_roots")
        parser = _ControlInventory(roots)
        parser.feed((ROOT / "static" / "index.html").read_text("utf-8"))
        self.assertGreaterEqual(len(parser.controls), 500)
        unmapped = [f"<{tag} id={control_id!r}>" for tag, control_id, owner in parser.controls if not owner]
        self.assertEqual(unmapped, [])
        self.assertEqual(set(roots), parser.seen_roots, "registry contains stale control roots")

    def test_generated_catalog_and_matrix_are_current(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_feature_catalog.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_every_automated_proof_reference_is_a_real_file(self):
        missing = []
        for feature in self.registry["features"]:
            for reference in feature["automated_tests"]:
                path = ROOT / reference
                if not path.is_file():
                    missing.append(f"{feature['id']}: {reference}")
        self.assertEqual(missing, [], "stale automated proof references:\n" + "\n".join(missing))

    def test_final_acceptance_has_no_unchecked_or_partial_rows(self):
        unfinished = [
            feature["id"]
            for feature in self.registry["features"]
            if feature["implementation"] != "shipped" or feature["acceptance"] == "unchecked"
        ]
        self.assertEqual(unfinished, [])
        self.assertTrue(all(feature.get("notes", "").strip() for feature in self.registry["features"]))


if __name__ == "__main__":
    unittest.main()
