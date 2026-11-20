"""Enforce inward dependencies as the invitation implementation evolves."""
import ast
import importlib.util
from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[1] / "app"


class DependencyDirectionTests(unittest.TestCase):
    def assert_dependencies(self, directory, allowed_app_modules):
        forbidden_packages = {"telethon", "fastapi", "sqlite3", "uvicorn", "pydantic"}
        for path in (APP / directory).rglob("*.py"):
            package = ".".join(path.relative_to(APP.parent).with_suffix("").parts[:-1])
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    module = "." * node.level + (node.module or "")
                    modules = [importlib.util.resolve_name(module, package)]
                    modules += [modules[0] + "." + alias.name for alias in node.names]
                else:
                    continue
                for module in modules:
                    with self.subTest(file=path.relative_to(APP), dependency=module):
                        self.assertNotIn(module.split(".")[0], forbidden_packages)
                        if module.startswith("app."):
                            self.assertTrue(any(
                                module == allowed or module.startswith(allowed + ".")
                                for allowed in allowed_app_modules
                            ), "Dependency must point inward")

    def test_domain_does_not_import_outer_layers(self):
        self.assert_dependencies("domain", ("app.domain",))

    def test_application_does_not_import_frameworks_or_adapters(self):
        self.assert_dependencies("application", ("app.domain", "app.application"))
