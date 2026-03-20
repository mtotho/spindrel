"""Auto-import all tool modules in this package to trigger @register decorators."""
import importlib
import pkgutil
from pathlib import Path

for _mod in pkgutil.iter_modules([str(Path(__file__).parent)]):
    importlib.import_module(f"app.tools.local.{_mod.name}")
