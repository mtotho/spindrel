"""Architecture guards for blocking startup bootstrap ownership."""
from __future__ import annotations

import ast
from pathlib import Path


def _async_function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _source_for(path: str, node: ast.AST) -> str:
    source = Path(path).read_text()
    return ast.get_source_segment(source, node) or ""


def test_main_lifespan_delegates_blocking_bootstrap_to_startup_module():
    source = Path("app/main.py").read_text()
    tree = ast.parse(source)
    lifespan = _async_function(tree, "lifespan")
    lifespan_source = _source_for("app/main.py", lifespan)

    assert "run_startup_bootstrap(" in lifespan_source
    assert "start_boot_background_services(" in lifespan_source
    assert "start_ready_runtime_services(" in lifespan_source

    boot_policy_needles = [
        "run_migrations",
        "seed_bots_from_yaml",
        "ensure_default_workspace",
        "ensure_all_bots_enrolled",
        "seed_manifests",
        "load_manifests",
        "discover_and_load_tools",
        "sync_all_files",
        "load_skills",
        "bootstrap_memory_scheme",
        "discover_integrations",
        "auto_register_from_manifest",
        "build_endpoint_catalog",
        "discover_web_uis",
    ]
    for needle in boot_policy_needles:
        assert needle not in lifespan_source


def test_startup_bootstrap_owns_blocking_bootstrap_policy_without_fastapi():
    source = Path("app/services/startup_bootstrap.py").read_text()
    tree = ast.parse(source)

    assert "async def run_startup_bootstrap" in source
    for needle in [
        "_cleanup_orphaned_tools",
        "run_migrations",
        "ensure_default_workspace",
        "ensure_all_bots_enrolled",
        "seed_manifests",
        "load_manifests",
        "discover_and_load_tools",
        "file_sync.sync_all_files",
        "bootstrap_memory_scheme",
        "application.include_router",
        "auto_register_from_manifest",
        "build_endpoint_catalog",
        "discover_web_uis",
    ]:
        assert needle in source

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "fastapi"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "fastapi"
