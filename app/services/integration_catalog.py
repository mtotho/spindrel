"""Integration catalog/status projection for admin surfaces."""
from __future__ import annotations

import importlib
import logging
import os
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)
_SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def discover_setup_status(base_url: str = "") -> list[dict]:
    """Return side-effect-free setup status for all integrations."""
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_process_config, get_setup

    results: list[dict] = []

    for candidate, integration_id, is_external, source in iter_integration_candidates():
        proc_cfg = get_process_config(candidate, integration_id, is_external, source)
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

        setup = get_setup(candidate, integration_id, is_external, source)
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
            binary_path = shutil.which(binary) or (
                os.path.join(npm_bin, binary)
                if os.path.isfile(os.path.join(npm_bin, binary))
                else None
            )
            installed = binary_path is not None and _npm_binary_satisfies_version(dep, binary_path)
        npm_status.append({
            "package": dep["package"],
            "binary_name": dep.get("binary_name", dep["package"]),
            "installed": installed,
            "minimum_version": dep.get("minimum_version"),
        })
        if not installed:
            all_npm_installed = False
    entry["npm_dependencies"] = npm_status
    entry["npm_deps_installed"] = all_npm_installed


def _npm_binary_satisfies_version(dep: dict, binary_path: str) -> bool:
    minimum_version = dep.get("minimum_version")
    if not minimum_version:
        return True

    version_command = dep.get("version_command")
    cmd = (
        [part for part in str(version_command).split() if part]
        if version_command
        else [binary_path, "--version"]
    )
    if cmd and cmd[0] == dep.get("binary_name"):
        cmd[0] = binary_path
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        logger.debug("Could not probe npm dependency version for %s", dep.get("package"), exc_info=True)
        return False
    if proc.returncode != 0:
        return False
    current = _parse_semver(proc.stdout or proc.stderr or "")
    required = _parse_semver(str(minimum_version))
    return current is not None and required is not None and current >= required


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.search(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


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


def discover_dashboard_modules() -> list[dict]:
    """Discover integration dashboard module declarations."""
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_setup

    results: list[dict] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        setup = get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        for mod in setup.get("dashboard_modules", []):
            results.append({
                "integration_id": integration_id,
                "module_id": mod["id"],
                "label": mod.get("label", mod["id"]),
                "icon": mod.get("icon", "Zap"),
                "description": mod.get("description", ""),
                "api_base": f"/integrations/{integration_id}/mc/{mod['id']}",
            })
    return results


_sidebar_sections_cache: list[dict] | None = None


def discover_sidebar_sections(*, refresh: bool = False) -> list[dict]:
    """Discover sidebar sections declared by integration manifests."""
    global _sidebar_sections_cache
    if _sidebar_sections_cache is not None and not refresh:
        return _sidebar_sections_cache

    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_setup

    results: list[dict] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        setup = get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        try:
            section = setup.get("sidebar_section")
            if section and isinstance(section, dict) and "id" in section and section.get("items"):
                results.append({
                    "integration_id": integration_id,
                    "id": section["id"],
                    "title": section.get("title", section["id"].upper()),
                    "icon": section.get("icon", "Plug"),
                    "items": [
                        item
                        for item in section["items"]
                        if isinstance(item, dict) and "label" in item and "href" in item
                    ],
                    "readiness_endpoint": section.get("readiness_endpoint"),
                    "readiness_field": section.get("readiness_field"),
                })
        except Exception:
            logger.exception("Failed to load sidebar section for integration %r", integration_id)

    _sidebar_sections_cache = results
    return results


_activation_manifests: dict[str, dict] | None = None


def _discover_activation_tools(candidate, integration_id: str) -> list[str]:
    """Best-effort tool list for activation manifests."""
    try:
        from app.tools.registry import _tools as registered_tools

        names = sorted(
            name
            for name, meta in registered_tools.items()
            if meta.get("source_integration") == integration_id
        )
        if names:
            return names
    except Exception:
        logger.debug("Failed to inspect tool registry for %s", integration_id, exc_info=True)

    tools_dir = candidate / "tools"
    if not tools_dir.is_dir():
        return []
    return sorted(f.stem for f in tools_dir.glob("*.py") if not f.name.startswith("_"))


def discover_activation_manifests() -> dict[str, dict]:
    """Discover and merge integration activation manifests."""
    global _activation_manifests
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_setup

    results: dict[str, dict] = {}
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        setup = get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        activation = setup.get("activation")
        if activation and isinstance(activation, dict):
            version = setup.get("version")
            if version and "version" not in activation:
                activation = {**activation, "version": version}
            if not activation.get("tools"):
                activation = {**activation, "tools": _discover_activation_tools(candidate, integration_id)}
            results[integration_id] = activation

    for _itype, manifest in results.items():
        includes = manifest.get("includes")
        if not includes or not isinstance(includes, list):
            continue
        merged_tools = list(manifest.get("tools", []))
        merged_config_fields = list(manifest.get("config_fields", []))
        existing_keys = {f["key"] for f in merged_config_fields}
        for included_id in includes:
            included = results.get(included_id)
            if not included:
                continue
            for tool_name in included.get("tools", []):
                if tool_name not in merged_tools:
                    merged_tools.append(tool_name)
            for field in included.get("config_fields", []):
                if field["key"] not in existing_keys:
                    merged_config_fields.append({**field, "source_integration": included_id})
                    existing_keys.add(field["key"])
        if merged_tools:
            manifest["tools"] = merged_tools
        if merged_config_fields:
            manifest["config_fields"] = merged_config_fields

    _activation_manifests = results
    return results


def get_activation_manifests() -> dict[str, dict]:
    """Return cached activation manifests, discovering if needed."""
    global _activation_manifests
    if _activation_manifests is None:
        return discover_activation_manifests()
    return _activation_manifests


def discover_web_uis() -> list[dict]:
    """Discover integrations that ship static web UI bundles."""
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_setup

    results: list[dict] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        setup = get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        web_ui = setup.get("web_ui")
        if not web_ui or not isinstance(web_ui, dict):
            continue
        static_dir = web_ui.get("static_dir")
        if not static_dir:
            continue
        static_path = (candidate / static_dir).resolve()
        if not static_path.is_dir():
            logger.warning(
                "Integration %r declares web_ui but static dir does not exist: %s "
                "(run 'npm run build' inside the dashboard directory)",
                integration_id,
                static_path,
            )
            continue
        results.append({
            "integration_id": integration_id,
            "static_dir_path": static_path,
            "dev_port": web_ui.get("dev_port"),
        })
        logger.info("Discovered web UI for integration %r: %s", integration_id, static_path)
    return results


def discover_binding_metadata() -> dict[str, dict]:
    """Return binding metadata for all integrations that declare it."""
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_setup

    results: dict[str, dict] = {}
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        setup = get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        binding = setup.get("binding")
        if binding:
            results[integration_id] = binding
    return results


def discover_integration_events() -> dict[str, list[dict]]:
    """Return declared events keyed by integration id."""
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_setup

    results: dict[str, list[dict]] = {}
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        setup = get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        events = setup.get("events")
        if events and isinstance(events, list):
            results[integration_id] = events
    return results


def discover_bindable_integration_types() -> set[str]:
    """Return integration ids that can appear as channel binding types."""
    from integrations.discovery import iter_integration_candidates

    types: set[str] = set(discover_binding_metadata().keys())
    for candidate, integration_id, _is_external, _source in iter_integration_candidates():
        if (candidate / "router.py").exists():
            types.add(integration_id)
    return types


def discover_docker_compose_stacks() -> list[dict]:
    """Discover integration Docker Compose stack declarations."""
    from app.config import settings as app_settings
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_setup

    def _interp(value):
        if not isinstance(value, str):
            return value
        return value.replace("${SPINDREL_INSTANCE_ID}", app_settings.SPINDREL_INSTANCE_ID or "default")

    results: list[dict] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        setup = get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        compose_config = setup.get("docker_compose")
        if not compose_config or not isinstance(compose_config, dict):
            continue

        compose_file = compose_config.get("file")
        if not compose_file:
            continue

        compose_path = candidate / compose_file
        if not compose_path.exists():
            logger.warning(
                "Integration %r declares docker_compose but file not found: %s",
                integration_id,
                compose_path,
            )
            continue

        config_files: dict[str, str] = {}
        for rel_path in compose_config.get("config_files", []):
            cfg_path = candidate / rel_path
            if cfg_path.exists():
                config_files[rel_path] = cfg_path.read_text()
            else:
                logger.warning(
                    "Integration %r docker_compose config_file not found: %s",
                    integration_id,
                    cfg_path,
                )

        enabled_setting = compose_config.get("enabled_setting")
        enabled_default = "false"
        if enabled_setting:
            for var in setup.get("env_vars", []):
                if var.get("key") == enabled_setting:
                    enabled_default = var.get("default", "false")
                    break

        results.append({
            "integration_id": integration_id,
            "project_name": _interp(compose_config.get("project_name", f"spindrel-{integration_id}")),
            "compose_definition": compose_path.read_text(),
            "config_files": config_files,
            "enabled_setting": enabled_setting,
            "enabled_default": enabled_default,
            "enabled_callable": None,
            "description": compose_config.get("description", ""),
        })
    return results


def discover_processes() -> list[dict]:
    """Discover runnable integration background processes."""
    from integrations.discovery import iter_integration_candidates
    from integrations.manifest_setup import get_process_config, resolve_cmd

    results: list[dict] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        proc_cfg = get_process_config(candidate, integration_id, is_external, source)
        if not proc_cfg:
            continue

        required_env = proc_cfg["required_env"]
        cmd = resolve_cmd(proc_cfg["cmd"], proc_cfg.get("watch_paths"))
        if all(os.environ.get(v) for v in required_env):
            results.append({
                "id": integration_id,
                "cmd": cmd,
                "required_env": required_env,
                "description": proc_cfg["description"],
            })
        else:
            missing = [v for v in required_env if not os.environ.get(v)]
            logger.debug("Skipping process for integration %r: missing env vars %s", integration_id, missing)
    return results
