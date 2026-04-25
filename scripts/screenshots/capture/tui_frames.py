"""Frame definitions for the setup.sh wizard captures.

Imports the live PROVIDERS list from scripts/setup.py so model menus stay in
sync with the wizard. Each builder returns a Frame for a specific moment in
the wizard's flow:

  setup-1                  — banner + prereq check + provider select
  setup-3-modelname        — model select (after picking OpenAI)
  setup-4-websearch-select — web search backend select
  setup-5-start            — final confirm + service-up output
"""
from __future__ import annotations

import ast
from pathlib import Path

from scripts.screenshots.capture.tui_render import Frame, Line


def _load_providers() -> list[dict]:
    """Parse PROVIDERS literal out of scripts/setup.py via AST.

    Importing setup.py at module level isn't viable — it constructs a
    questionary `Style(...)` at top-level and exits if questionary isn't
    installed. Parsing the source extracts the same authoritative list
    without depending on the wizard's runtime deps.
    """
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "scripts" / "setup.py").read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PROVIDERS":
                    return ast.literal_eval(node.value)
    raise RuntimeError("PROVIDERS literal not found in scripts/setup.py")


PROVIDERS = _load_providers()


def _banner_lines() -> list[Line]:
    return [
        Line.blank(),
        Line.of("  ┌─────────────────────────────────┐", color="fg_bold", bold=True),
        Line.of("  │         s p i n d r e l          │", color="fg_bold", bold=True),
        Line.of("  │     self-hosted ai agent server  │", color="fg_bold", bold=True),
        Line.of("  └─────────────────────────────────┘", color="fg_bold", bold=True),
        Line.of("    your entire RAG loop, silk-wrapped.", color="fg_dim"),
        Line.blank(),
    ]


def _prereq_lines() -> list[Line]:
    return [
        Line.of("Checking prerequisites...", color="cyan"),
        Line.of("✓ All prerequisites met (Python 3.12, docker compose)", color="green"),
        Line.blank(),
    ]


def _select_lines(
    prompt: str,
    choices: list[str],
    selected_idx: int = 0,
    *,
    show_hint: bool = True,
) -> list[Line]:
    lines: list[Line] = []
    header = Line.of("? ", color="prompt", bold=True).then(prompt, bold=True)
    if show_hint:
        header.then("  (Use arrow keys)", color="fg_dim")
    lines.append(header)
    for i, choice in enumerate(choices):
        if i == selected_idx:
            line = Line.of(" » ", color="cyan", bold=True).then(choice, color="cyan", bold=True)
            line.highlight = True
            lines.append(line)
        else:
            lines.append(Line.of("   " + choice, color="fg"))
    return lines


def _answered_lines(qa_pairs: list[tuple[str, str]]) -> list[Line]:
    out: list[Line] = []
    for q, a in qa_pairs:
        line = Line.of("? ", color="prompt", bold=True).then(q + " ", bold=True)
        line.then(a, color="cyan", bold=True)
        out.append(line)
    return out


def setup_1() -> Frame:
    """Banner + prereq check + provider list, first item highlighted."""
    lines = _banner_lines() + _prereq_lines()
    lines += _answered_lines([("Deployment mode:", "Docker (recommended)")])
    provider_labels = [p["label"] for p in PROVIDERS] + ["Skip — configure in UI later"]
    lines += _select_lines("LLM Provider:", provider_labels, selected_idx=1)
    return Frame(lines=lines, title="bash setup.sh — provider selection")


def setup_3_modelname() -> Frame:
    """Model selection after picking OpenAI."""
    lines = _banner_lines()[:5]
    lines.append(Line.blank())
    openai = next(p for p in PROVIDERS if p["id"] == "openai")
    lines += _answered_lines([
        ("Deployment mode:", "Docker (recommended)"),
        ("LLM Provider:", "OpenAI"),
        ("API key:", "************************"),
    ])
    model_choices = list(openai["models"]) + ["Enter custom model"]
    lines += _select_lines("Default model:", model_choices, selected_idx=0)
    return Frame(lines=lines, title="bash setup.sh — model selection")


def setup_4_websearch_select() -> Frame:
    """Web search backend select."""
    lines = _banner_lines()[:5]
    lines.append(Line.blank())
    lines += _answered_lines([
        ("Deployment mode:", "Docker (recommended)"),
        ("LLM Provider:", "OpenAI"),
        ("API key:", "************************"),
        ("Default model:", "gpt-5.5"),
    ])
    web_choices = [
        "SearXNG — built-in containers (adds 2 containers)",
        "SearXNG — external (bring your own instance)",
        "DuckDuckGo — lightweight, no extra containers",
        "None — I'll add my own search tool",
    ]
    lines += _select_lines("Web search backend:", web_choices, selected_idx=0)
    return Frame(lines=lines, title="bash setup.sh — web search backend")


def setup_5_start() -> Frame:
    """Final confirm + service-up output."""
    lines: list[Line] = []
    lines += _answered_lines([
        ("Default model:", "gpt-5.5"),
        ("Web search backend:", "SearXNG — built-in containers"),
        ("Auth API key:", "Generate random key (sk-spi-9b41…)"),
    ])
    lines.append(Line.blank())
    lines.append(Line.of("  Next steps:", bold=True))
    lines.append(Line.of("  1. docker compose up -d"))
    lines.append(Line.of("  2. Open http://localhost:8000"))
    lines.append(Line.of("  3. The Orchestrator will greet you and walk you through setup."))
    lines.append(Line.blank())
    confirm = Line.of("? ", color="prompt", bold=True).then("Start docker compose now? ", bold=True)
    confirm.then("Yes", color="cyan", bold=True)
    lines.append(confirm)
    lines.append(Line.blank())
    lines.append(Line.of("  provider-seed.yaml will be consumed on first server boot", color="fg_dim"))
    lines.append(Line.of("  ✓ ", color="green", bold=True).then("Spindrel running at ").then("http://localhost:8000", bold=True))
    lines.append(Line.blank())
    lines.append(Line.of("  ✓ ", color="green", bold=True).then("CLI installed. Commands:"))
    lines.append(Line.of("    spindrel status    — Show service status", color="fg_dim"))
    lines.append(Line.of("    spindrel restart   — Restart services", color="fg_dim"))
    lines.append(Line.of("    spindrel logs      — Tail logs", color="fg_dim"))
    lines.append(Line.of("    spindrel pull      — Git pull + rebuild + restart", color="fg_dim"))
    return Frame(lines=lines, title="bash setup.sh — services up")


SETUP_TUI_FRAMES = {
    "setup-1": setup_1,
    "setup-3-modelname": setup_3_modelname,
    "setup-4-websearch-select": setup_4_websearch_select,
    "setup-5-start": setup_5_start,
}
