"""Plugin installer — namespace-aware install/uninstall of plugin bundles.

Two install paths:
  - ``install(source_dir)``     — from a local plugin bundle directory.
  - ``install_from_marketplace(name, alias)`` — resolve a plugin's relative
    ``source`` inside a locally cloned marketplace, then install.

Assets are copied into ``~/.code/plugins/installed/<marketplace>/<plugin>/``
with ``agents/``, ``skills/``, and ``commands/`` subfolders — namespaced by the
marketplace alias (Claude Code convention) so plugins from different
marketplaces never collide in the raw global agents/skills dirs. MCP servers
are merged into settings.json ``mcpServers`` under a ``<marketplace>-<server>``
key so server names stay namespaced too.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from harness.config import (
    load_settings_file,
    save_settings_file,
)
from harness.plugins.marketplace import fetch_catalog
from harness.plugins.models import InstalledPlugin, PluginManifest
from harness.plugins.state import (
    load_state,
    save_state,
    installed_plugins_dir,
)

# Manifest file names inside a plugin's source dir, in discovery order.
_MANIFEST_CANDIDATES = (".claude-plugin/plugin.json", "plugin.json")


def _locate_manifest(source_dir: Path) -> Path | None:
    for rel in _MANIFEST_CANDIDATES:
        candidate = source_dir / rel
        if candidate.is_file():
            return candidate
    return None


def _copy_md_files(src_dir: Path, dst_dir: Path) -> list[str]:
    """Copy every ``*.md`` under src_dir (subdirs included) into dst_dir.

    Claude Code skills live under ``skills/<name>/SKILL.md``, so the whole
    relative tree is preserved. Returns the copied relative paths.
    """
    if not src_dir.is_dir():
        return []
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for path in sorted(src_dir.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir)
        target = dst_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(rel.as_posix())
    return copied


def _collect_mcp(manifest: PluginManifest, source_dir: Path) -> dict:
    """MCP servers: plugin.json ``mcp.servers`` merged with repo-root ``.mcp.json``."""
    servers = dict(manifest.mcp.get("servers", {}) or {})
    mcp_json = source_dir / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        servers.update(data.get("mcpServers", {}) or {})
    return servers


class PluginInstaller:
    """Install, uninstall, and list plugin bundles (namespaced by marketplace)."""

    def install(
        self,
        source_dir: Path,
        marketplace: str = "",
        name: str | None = None,
    ) -> InstalledPlugin:
        """Install a bundle from a local plugin source directory.

        ``source_dir`` is the plugin's root: contains ``.claude-plugin/plugin.json``
        (or ``plugin.json``) plus ``agents/``, ``skills/``, ``commands/``.
        Agents are auto-discovered from ``agents/*.md`` by convention.

        ``name`` optionally overrides the installed name (used by marketplace
        installs to key the plugin by its catalog ``name``). Assets are copied
        under ``installed/<marketplace>/<name>/``.
        """
        manifest_path = _locate_manifest(source_dir)
        if manifest_path is None:
            raise ValueError(
                f"No plugin manifest in {source_dir} "
                "(expected .claude-plugin/plugin.json)"
            )
        manifest = PluginManifest.from_file(manifest_path)
        namespace = marketplace or manifest.name
        plugin_name = name or manifest.name

        state = load_state()
        installed = state.setdefault("installed", {})
        if plugin_name in installed:
            raise ValueError(
                f"Plugin '{plugin_name}' is already installed "
                f"(marketplace '{installed[plugin_name].get('marketplace', '')}'). "
                "Run uninstall first."
            )

        dest_root = installed_plugins_dir() / namespace / plugin_name
        dest_root.mkdir(parents=True, exist_ok=True)

        # 1. Agents — convention: agents/*.md (not declared in plugin.json).
        agent_dir = source_dir / "agents"
        agent_names = _copy_md_files(agent_dir, dest_root / "agents")

        # 2. Skills — each declared dir copied shallow.
        skill_names: list[str] = []
        for rel in manifest.skills or [""]:
            if not rel:
                continue
            skill_names.extend(
                _copy_md_files(source_dir / rel, dest_root / "skills")
            )

        # 3. Commands — each declared dir copied shallow.
        command_names: list[str] = []
        for rel in manifest.commands or []:
            command_names.extend(
                _copy_md_files(source_dir / rel, dest_root / "commands")
            )

        # 3b. Instructions + rules — convention dirs or manifest-declared dirs
        # (like skills: "" resolves to the source root).
        instruction_names: list[str] = []
        for rel in manifest.instructions or [""]:
            if not rel:
                continue
            instruction_names.extend(
                _copy_md_files(source_dir / rel, dest_root / "instructions")
            )
        rule_names: list[str] = []
        for rel in manifest.rules or [""]:
            if not rel:
                continue
            rule_names.extend(
                _copy_md_files(source_dir / rel, dest_root / "rules")
            )

        # 4. MCP servers → settings.json, namespaced `{recipe}-{server}`.
        mcp_servers = _collect_mcp(manifest, source_dir)
        installed_servers: list[str] = []
        if mcp_servers:
            data = load_settings_file()
            servers = data.setdefault("mcpServers", {})
            for server_name, cfg in mcp_servers.items():
                key = f"{namespace}-{server_name}"
                servers[key] = cfg
                installed_servers.append(key)
            save_settings_file()

        # 5. Record installation in state.
        record = InstalledPlugin(
            name=plugin_name,
            version=manifest.version,
            marketplace=namespace,
            agent_names=agent_names,
            skill_names=skill_names,
            command_names=command_names,
            instruction_names=instruction_names,
            rule_names=rule_names,
            mcp_server_names=installed_servers,
            installed_at=datetime.now().isoformat(timespec="seconds"),
        )
        installed[plugin_name] = record.to_dict()
        save_state(state)
        return record

    def install_from_marketplace(
        self, name: str, marketplace_alias: str
    ) -> InstalledPlugin:
        """Install a plugin from a registered marketplace's local clone.

        The catalog is read from the local clone (no network), the plugin's
        ``source`` is resolved relative to that clone, and ``install()`` copies
        its assets with the marketplace alias as the namespace.
        """
        catalog = fetch_catalog(marketplace_alias)
        if catalog is None:
            raise ValueError(
                f"Marketplace '{marketplace_alias}' is not registered. "
                "Run `harness plugin marketplace add <url-or-repo>` first."
            )

        plugin = catalog.search(name)
        if plugin is None:
            available = ", ".join(p.name for p in catalog.plugins) or "(empty)"
            raise ValueError(
                f"Plugin '{name}' not found in marketplace "
                f"'{marketplace_alias}'. Available plugins: {available}"
            )

        source_dir = catalog.resolve_source(plugin)
        if not source_dir.is_dir():
            raise ValueError(
                f"Source dir '{plugin.source}' for plugin '{name}' is missing "
                f"inside marketplace '{marketplace_alias}' (clone may be stale; "
                "re-run plugin marketplace add)."
            )
        return self.install(source_dir, marketplace=marketplace_alias, name=plugin.name)

    def uninstall(self, name: str) -> bool:
        """Remove a plugin by name. Returns False if not installed."""
        state = load_state()
        installed = state.get("installed", {})
        if name not in installed:
            return False

        record = InstalledPlugin.from_dict(installed[name])
        namespace = record.marketplace or record.name

        # Remove the namespaced install area.
        shutil.rmtree(
            installed_plugins_dir() / namespace / name, ignore_errors=True
        )

        # Remove namespaced MCP servers from settings.json.
        if record.mcp_server_names:
            data = load_settings_file()
            servers = data.get("mcpServers") or {}
            for sname in record.mcp_server_names:
                servers.pop(sname, None)
            save_settings_file()

        del installed[name]
        save_state(state)
        return True

    def list_installed(self) -> list[InstalledPlugin]:
        state = load_state()
        return [
            InstalledPlugin.from_dict(rec)
            for rec in state.get("installed", {}).values()
        ]