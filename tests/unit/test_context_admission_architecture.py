"""Architecture guards for context admission ownership."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_ASSEMBLY = REPO_ROOT / "app" / "agent" / "context_assembly.py"
CONTEXT_ADMISSION = REPO_ROOT / "app" / "agent" / "context_admission.py"


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path}: missing function {name}")


def test_context_admission_owns_static_admission_policy():
    source = CONTEXT_ADMISSION.read_text()

    for needle in (
        "channel_workspace_tools",
        "MEMORY.md",
        "build_plan_artifact_context",
        "resolve_channel_work_surface",
        "retrieve_filesystem_context",
        "ConversationSection",
        "get_bot_knowledge_base_index_prefix",
        "workspace_rag",
        "bot_knowledge_base",
        "channel_index_segments",
        "section_index",
    ):
        assert needle in source


def test_assemble_context_does_not_reabsorb_static_admission_policy():
    source = CONTEXT_ASSEMBLY.read_text()
    assemble_source = ast.get_source_segment(source, _function_node(CONTEXT_ASSEMBLY, "assemble_context")) or ""

    assert "apply_channel_workspace_tools" in assemble_source
    for forbidden in (
        "CHANNEL_WORKSPACE_TOOLS",
        "_CHANNEL_WORKSPACE_BUDGET",
        "retrieve_filesystem_context",
        "ConversationSection",
        "get_memory_root",
        "build_plan_artifact_context",
        "get_bot_knowledge_base_index_prefix",
        "reindex_channel",
    ):
        assert forbidden not in assemble_source


def test_context_assembly_private_admission_wrappers_stay_small():
    source = CONTEXT_ASSEMBLY.read_text()
    for name in (
        "_render_channel_workspace_prompt",
        "_inject_plan_artifact",
        "_inject_memory_scheme",
        "_inject_channel_workspace",
        "_inject_conversation_sections",
        "_inject_workspace_rag",
        "_inject_bot_knowledge_base",
    ):
        node = _function_node(CONTEXT_ASSEMBLY, name)
        assert node.end_lineno is not None
        loc = node.end_lineno - node.lineno + 1
        assert loc <= 42
        wrapper_source = ast.get_source_segment(source, node) or ""
        assert "app.agent.context_admission" in wrapper_source


def test_context_admission_is_not_a_router_or_diagnostics_module():
    source = CONTEXT_ADMISSION.read_text()

    for forbidden in (
        "from fastapi",
        "APIRouter",
        "compute_context_breakdown",
        "context_breakdown_response",
    ):
        assert forbidden not in source


def test_context_admission_does_not_launch_indexing_work():
    source = CONTEXT_ADMISSION.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "reindex_channel":
            raise AssertionError("context admission must not reindex during chat request handling")
        if isinstance(func, ast.Attribute) and func.attr == "reindex_channel":
            raise AssertionError("context admission must not reindex during chat request handling")
