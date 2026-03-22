"""Auto-import all tool modules in this package via the file loader so that
@register captures the correct source_file for each module."""
from pathlib import Path

_local_dir = Path(__file__).parent

for _py_file in sorted(_local_dir.glob("*.py")):
    if not _py_file.name.startswith("_"):
        from app.tools.loader import _import_tool_file
        _import_tool_file(_py_file)
