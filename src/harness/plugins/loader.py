"""Startup loader — mounts installed plugins' agents/skills into the registries.

Plugin agents/skills are NOT copied into the raw global ``~/.code/agents`` /
``~/.code/skills`` dirs. They live namespaced under
``~/.code/plugins/installed/<marketplace>/<plugin>/`` and are mounted here as
*namespaced scan roots*, so they surface in the LLM roster as
``<marketplace>-<name>`` — matching Claude Code's convention of prefixing each
plugin asset with its marketplace alias to avoid collisions.

Called once at startup from ``HarnessOrchestrator.ensure_session``.
"""

import logging
from pathlib import Path

from harness.plugins.state import installed_plugins_dir, load_state

logger = logging.getLogger(__name__)


def load_installed_plugins(agent_registry=None, skill_registry=None) -> int:
    """Mount each installed plugin's ``agents/`` and ``skills/`` as namespaced roots.

    Pass the harness :class:`AgentRegistry`/`SkillRegistry` to surface plugin
    agents and skills in the roster as ``<marketplace>-<name>``. Dirs that
    don't exist (e.g. a plugin without skills) are skipped. Returns the number
    of plugins registered.
    """
    installed = (load_state().get("installed") or {}).values()
    mounted = 0
    for record in installed:
        name = record.get("name")
        if not name:
            continue
        namespace = record.get("marketplace") or name
        plugin_dir = installed_plugins_dir() / namespace / name
        if agent_registry is not None:
            agent_registry.add_scope_root(plugin_dir / "agents", prefix=namespace)
        if skill_registry is not None:
            skill_registry.add_scope_root(plugin_dir / "skills", prefix=namespace)
        mounted += 1
    logger.info("Plugin loader mounted %d installed plugin(s)", mounted)
    return mounted


def _frontmatter_description(path: Path) -> str:
    """Extract ``description:`` from a leading frontmatter block, else ``""``."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    for line in text.splitlines()[1:]:
        if line == "---":
            break
        if line.lower().startswith("description:"):
            return line.split(":", 1)[1].strip()
    return ""


def collect_plugin_commands() -> list[dict]:
    """Enumerate every installed plugin's ``commands/*.md`` files.

    Returns ``[{name, description, path, plugin}]`` where ``name`` is the file
    stem (slash-command name) and ``plugin`` is the namespaced label
    ``<marketplace>-<plugin>``. Used to mount plugin commands in the UI palette.
    """
    out: list[dict] = []
    for record in (load_state().get("installed") or {}).values():
        name = record.get("name")
        if not name:
            continue
        namespace = record.get("marketplace") or name
        commands_dir = installed_plugins_dir() / namespace / name / "commands"
        if not commands_dir.is_dir():
            continue
        for path in sorted(commands_dir.rglob("*.md")):
            out.append(
                {
                    "name": path.stem,
                    "description": _frontmatter_description(path),
                    "path": str(path),
                    "plugin": f"{namespace}-{name}",
                }
            )
    return out


def collect_plugin_catalog() -> list[dict]:
    """Cheap per-plugin asset counts from the state records (no disk scan).

    Returns ``[{name, commands, instructions, rules}]`` for the orchestrator's
    ``<available_plugins>`` roster block.
    """
    out: list[dict] = []
    for record in (load_state().get("installed") or {}).values():
        rname = record.get("name")
        if not rname:
            continue
        namespace = record.get("marketplace") or rname
        out.append(
            {
                "name": f"{namespace}-{rname}",
                "commands": len(record.get("command_names") or []),
                "instructions": len(record.get("instruction_names") or []),
                "rules": len(record.get("rule_names") or []),
            }
        )
    return out