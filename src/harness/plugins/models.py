"""Data models for plugin manifests and plugin records.

Schema mirrors the Claude Code plugin convention:
- A marketplace.json catalog lives at ``<clone>/.claude-plugin/marketplace.json``.
- Catalog ``plugins`` entries reference a plugin *source directory* inside the
  marketplace clone via a relative ``source`` (e.g. ``"./"``) — not a URL.
- Each plugin dir carries its own ``.claude-plugin/plugin.json``.
- Agents are auto-discovered from ``agents/*.md`` by convention (not declared).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


def _as_path_list(value: Any) -> list[str]:
    """Normalize a manifest dir field (string path or list of paths) to a list.

    Claude Code plugin.json files declare skills/commands as either a single
    string (``"skills": "./skills/"``) or a list; both must survive install.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(v).strip() for v in value if str(v).strip()]


@dataclass
class PluginManifest:
    """Describes a plugin: MCP servers + agents/skills/commands asset dirs.

    ``agents``/``skills``/``commands`` are relative paths resolved against the
    plugin's source directory. Agents are convention-discovered, so a manifest
    normally declares only skills/commands dirs; ``agents`` is populated at
    load time from ``agents/``.
    """
    name: str
    version: str
    description: str
    mcp: dict[str, Any] = field(default_factory=dict)   # {"servers": {name: config}}
    agents: list[str] = field(default_factory=list)      # relative paths to .md
    skills: list[str] = field(default_factory=list)      # relative dirs ("" = source root)
    commands: list[str] = field(default_factory=list)    # relative dirs
    instructions: list[str] = field(default_factory=list)  # relative dirs ("" = source root)
    rules: list[str] = field(default_factory=list)         # relative dirs ("" = source root)

    @classmethod
    def from_file(cls, path: Path) -> "PluginManifest":
        data = json.loads(path.read_text(encoding="utf-8"))

        # Claude Code manifests commonly declare MCP servers at the top level
        # ("mcpServers") rather than nested under "mcp"; fold both forms in.
        mcp = dict(data.get("mcp", {}) or {})
        servers = dict(mcp.get("servers", {}) or {})
        servers.update(data.get("mcpServers", {}) or {})
        mcp["servers"] = servers

        return cls(
            name=data["name"],
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            mcp=mcp,
            agents=_as_path_list(data.get("agents")),
            skills=_as_path_list(data.get("skills")),
            commands=_as_path_list(data.get("commands")),
            instructions=_as_path_list(data.get("instructions")),
            rules=_as_path_list(data.get("rules")),
        )


@dataclass
class InstalledPlugin:
    """Record of an installed plugin, persisted in the state file.

    A plugin is installed *namespaced*: its agents/skills/commands live under
    ``installed/<marketplace>/<name>/`` relative to the plugin dirs, and names
    are surfaced to the LLM context prefixed with the marketplace alias.
    """
    name: str
    version: str
    marketplace: str = ""                       # alias it came from
    agent_names: list[str] = field(default_factory=list)   # basenames installed
    skill_names: list[str] = field(default_factory=list)
    command_names: list[str] = field(default_factory=list)
    instruction_names: list[str] = field(default_factory=list)
    rule_names: list[str] = field(default_factory=list)
    mcp_server_names: list[str] = field(default_factory=list)
    installed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "marketplace": self.marketplace,
            "agent_names": self.agent_names,
            "skill_names": self.skill_names,
            "command_names": self.command_names,
            "instruction_names": self.instruction_names,
            "rule_names": self.rule_names,
            "mcp_server_names": self.mcp_server_names,
            "installed_at": self.installed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InstalledPlugin":
        return cls(
            name=d["name"],
            version=d.get("version", "0.0.0"),
            marketplace=d.get("marketplace", ""),
            agent_names=d.get("agent_names", []),
            skill_names=d.get("skill_names", []),
            command_names=d.get("command_names", []),
            instruction_names=d.get("instruction_names", []),
            rule_names=d.get("rule_names", []),
            mcp_server_names=d.get("mcp_server_names", []),
            installed_at=d.get("installed_at", ""),
        )