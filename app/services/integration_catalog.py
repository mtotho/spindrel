"""Integration catalog/status projection for admin surfaces."""
from __future__ import annotations

import importlib
import logging
import os

logger = logging.getLogger(__name__)


def discover_setup_status(base_url: str = "") -> list[dict]:
    """Return side-effect-free setup status for all integrations."""
    from integrations import _get_process_config, _get_setup, _iter_integration_candidates

    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        proc_cfg = _get_process_config(candidate, integration_id, is_external, source)
        has_process = proc_cfg is not None
        entry: dict = {
            "id": integration_id,
            "name": integration_id.replace("_", " ").replace("-", " ").title(),
            "source": source,
            "icon": "Plug",
            "has_router": (candidate / "router.py").exists(),
            "has_dispatcher": False,
            "has_renderer": (candidate / "renderer.py").exists(),
            "has_hooks": (candidate / "hooks.py").exists(),
            "has_tools": any((candidate / "tools").glob("*.py")) if (candidate / "tools").is_dir() else False,
            "has_skills": any((candidate / "skills").glob("**/*.md")) if (candidate / "skills").is_dir() else False,
            "has_process": has_process,
            "process_launchable": has_process,
            "process_description": proc_cfg["description"] if proc_cfg else None,
            "process_status": None,
            "env_vars": [],
            "webhook": None,
            "api_permissions": None,
            "provides": [],
            "runtime_services": None,
            "machine_control": None,
            "status": "not_configured",
            "readme": None,
        }

        _apply_tool_and_skill_inventory(entry, candidate, integration_id)
        _apply_widget_inventory(entry, integration_id)
        _apply_lifecycle_and_process_status(entry, integration_id, has_process)

        setup = _get_setup(candidate, integration_id, is_external, source)
        entry["has_yaml"] = (candidate / "integration.yaml").exists()
        if setup:
            _apply_setup_fields(entry, candidate, integration_id, setup, base_url)

        _apply_readme(entry, candidate)
        _apply_readiness_status(entry)
        results.append(entry)

    return results


def _apply_tool_and_skill_inventory(entry: dict, candidate, integration_id: str) -> None:
    try:
        from app.tools.registry import _tools as registered_tools

        entry["tool_names"] = sorted(
            name
            for name, meta in registered_tools.items()
            if meta.get("source_integration") == integration_id
        )
    except Exception:
        entry["tool_names"] = []

    tools_dir = candidate / "tools"
    entry["tool_files"] = (
        sorted(f.stem for f in tools_dir.glob("*.py") if not f.name.startswith("_"))
        if tools_dir.is_dir()
        else []
    )

    skills_dir = candidate / "skills"
    entry["skill_files"] = (
        sorted(f.stem for f in skills_dir.glob("**/*.md"))
        if skills_dir.is_dir()
        else []
    )


def _apply_widget_inventory(entry: dict, integration_id: str) -> None:
    tool_widget_names: list[str] = []
    try:
        from app.services.integration_manifests import get_manifest

        manifest = get_manifest(integration_id)
        if manifest and isinstance(manifest.get("tool_widgets"), dict):
            tool_widget_names = sorted(manifest["tool_widgets"].keys())
    except Exception:
        pass
    entry["has_tool_widgets"] = len(tool_widget_names) > 0
    entry["tool_widget_names"] = tool_widget_names


def _apply_lifecycle_and_process_status(entry: dict, integration_id: str, has_process: bool) -> None:
    try:
        from app.services.integration_settings import get_status

        entry["lifecycle_status"] = get_status(integration_id)
    except Exception:
        entry["lifecycle_status"] = "available"

    if has_process:
        try:
            from app.services.integration_processes import process_manager

            entry["process_status"] = process_manager.status(integration_id)
        except ImportError:
            pass


def _apply_setup_fields(entry: dict, candidate, integration_id: str, setup: dict, base_url: str) -> None:
    entry["icon"] = setup.get("icon", "Plug")
    _apply_env_vars(entry, integration_id, setup)
    _apply_python_dependencies(entry, setup)
    _apply_npm_dependencies(entry, candidate, setup)
    _apply_system_dependencies(entry, setup)

    for key in ("oauth", "debug_actions"):
        value = setup.get(key)
        if value:
            entry[key] = value

    api_permissions = setup.get("api_permissions")
    if api_permissions:
        entry["api_permissions"] = api_permissions

    provides = setup.get("provides")
    if isinstance(provides, list):
        entry["provides"] = [str(v) for v in provides if str(v).strip()]

    runtime_services = setup.get("runtime_services")
    if isinstance(runtime_services, dict):
        entry["runtime_services"] = runtime_services

    machine_control = setup.get("machine_control")
    if isinstance(machine_control, dict):
        entry["machine_control"] = {
            "provider_id": str(machine_control.get("provider_id") or integration_id),
            "label": str(machine_control.get("label") or entry["name"]),
            "driver": str(machine_control.get("driver") or "unknown"),
            "profile_fields": (
                machine_control.get("profile_fields")
                if isinstance(machine_control.get("profile_fields"), list)
                else None
            ),
            "profile_setup_guide": (
                machine_control.get("profile_setup_guide")
                if isinstance(machine_control.get("profile_setup_guide"), dict)
                else None
            ),
            "enroll_fields": (
                machine_control.get("enroll_fields")
                if isinstance(machine_control.get("enroll_fields"), list)
                else None
            ),
            "metadata": (
                machine_control.get("metadata")
                if isinstance(machine_control.get("metadata"), dict)
                else None
            ),
        }

    webhook = setup.get("webhook")
    if webhook:
        full_url = f"{base_url.rstrip('/')}{webhook['path']}" if base_url else webhook["path"]
        entry["webhook"] = {
            "path": webhook["path"],
            "url": full_url,
            "description": webhook.get("description", ""),
        }

    for key in ("mcp_servers", "events"):
        value = setup.get(key)
        if value and isinstance(value, list):
            entry[key] = value


def _apply_env_vars(entry: dict, integration_id: str, setup: dict) -> None:
    for var in setup.get("env_vars", []):
        try:
            from app.services.integration_settings import get_value

            is_set = bool(get_value(integration_id, var["key"])) or bool(var.get("default"))
        except ImportError:
            is_set = bool(os.environ.get(var["key"])) or bool(var.get("default"))
        entry["env_vars"].append({
            "key": var["key"],
            "required": var.get("required", False),
            "description": var.get("description", ""),
            "default": var.get("default"),
            "is_set": is_set,
        })


def _apply_python_dependencies(entry: dict, setup: dict) -> None:
    py_deps = setup.get("python_dependencies", [])
    if not py_deps:
        return
    deps_status = []
    all_installed = True
    for dep in py_deps:
        import_name = dep.get("import_name", dep.get("package", "").replace("-", "_"))
        try:
            importlib.import_module(import_name)
            deps_status.append({"package": dep["package"], "installed": True})
        except ImportError:
            deps_status.append({"package": dep["package"], "installed": False})
            all_installed = False
    entry["python_dependencies"] = deps_status
    entry["deps_installed"] = all_installed


def _apply_npm_dependencies(entry: dict, candidate, setup: dict) -> None:
    npm_deps = setup.get("npm_dependencies", [])
    if not npm_deps:
        return
    import shutil

    npm_bin = os.path.expanduser("~/.local/bin")
    npm_status = []
    all_npm_installed = True
    for dep in npm_deps:
        check_path = dep.get("check_path")
        if check_path:
            if not os.path.isabs(check_path):
                check_path = os.path.join(str(candidate), check_path)
            installed = os.path.exists(check_path)
        else:
            binary = dep.get("binary_name", dep["package"])
            installed = shutil.which(binary) is not None or os.path.isfile(os.path.join(npm_bin, binary))
        npm_status.append({
            "package": dep["package"],
            "binary_name": dep.get("binary_name", dep["package"]),
            "installed": installed,
        })
        if not installed:
            all_npm_installed = False
    entry["npm_dependencies"] = npm_status
    entry["npm_deps_installed"] = all_npm_installed


def _apply_system_dependencies(entry: dict, setup: dict) -> None:
    sys_deps = setup.get("system_dependencies", [])
    if not sys_deps:
        return
    import shutil

    sys_status = []
    all_sys_installed = True
    for dep in sys_deps:
        binary = dep.get("binary", "")
        found = False
        for candidate_bin in [binary, *dep.get("alternatives", [])]:
            if shutil.which(candidate_bin):
                found = True
                break
        sys_status.append({
            "binary": binary,
            "apt_package": dep.get("apt_package", binary),
            "install_hint": dep.get("install_hint", ""),
            "installed": found,
        })
        if not found:
            all_sys_installed = False
    entry["system_dependencies"] = sys_status
    entry["system_deps_installed"] = all_sys_installed


def _apply_readme(entry: dict, candidate) -> None:
    readme_file = candidate / "README.md"
    if not readme_file.exists():
        return
    try:
        entry["readme"] = readme_file.read_text()[:5000]
    except Exception:
        pass


def _apply_readiness_status(entry: dict) -> None:
    required_vars = [v for v in entry["env_vars"] if v["required"]]
    deps_ok = (
        entry.get("deps_installed", True)
        and entry.get("npm_deps_installed", True)
        and entry.get("system_deps_installed", True)
    )
    if not required_vars:
        if entry["has_router"] or entry["has_dispatcher"] or entry["has_renderer"] or entry["has_hooks"] or entry["has_tools"]:
            entry["status"] = "ready" if deps_ok else "partial"
        return

    set_count = sum(1 for v in required_vars if v["is_set"])
    if set_count == len(required_vars) and deps_ok:
        entry["status"] = "ready"
    elif set_count > 0 or not deps_ok:
        entry["status"] = "partial"
