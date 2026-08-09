"""Marketplace registry — clone-local, source-relative plugin catalogs.

A "marketplace" is a git repo that ships a catalog plus the plugins themselves.
``plugin marketplace add`` **clones the whole repo** into
``~/.code/plugins/marketplaces/<name>/``, where ``name`` is the marketplace's
own ``name`` from its ``.claude-plugin/marketplace.json`` (or an explicit
``--alias``). The catalog is discovered at ``.claude-plugin/marketplace.json``
(falling back to the clone root). Catalog ``plugins`` entries reference a
*source directory* inside the clone via a relative ``source`` (e.g. ``"./"``),
so installs resolve against the local clone — no per-plugin network fetch.
"""

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.plugins import downloader
from harness.plugins.state import (
    load_state,
    save_state,
    update_state,
    marketplaces_dir,
)

# Catalog file names, in discovery order (Claude Code convention first).
_CATALOG_CANDIDATES = (".claude-plugin/marketplace.json", "marketplace.json")

# plugin.json location inside a plugin's source dir.
_PLUGIN_MANIFEST_CANDIDATES = (".claude-plugin/plugin.json", "plugin.json")

# GitHub repo shorthand/full URL: owner/repo (no protocol) or https://github.com/...
_GITHUB_RE = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")


@dataclass
class MarketplaceRecord:
    """A registered marketplace's persisted metadata (refers to a local clone)."""
    name: str
    url: str                            # clone source (repo URL or catalog URL)
    path: str = ""                      # absolute local clone/catalog dir
    catalog: str = "marketplace.json"   # catalog path relative to `path`
    added_at: str = ""

    @property
    def catalog_path(self) -> Path | None:
        """Absolute path to the marketplace.json catalog file, if it exists."""
        if not self.path:
            return None
        root = Path(self.path)
        candidate = (root / self.catalog) if self.catalog else None
        if candidate and candidate.is_file():
            return candidate
        for rel in _CATALOG_CANDIDATES:
            exist = root / rel
            if exist.is_file():
                return exist
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "path": self.path,
            "catalog": self.catalog,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MarketplaceRecord":
        return cls(
            name=d.get("name", ""),
            url=d.get("url", ""),
            path=d.get("path", ""),
            catalog=d.get("catalog", "marketplace.json"),
            added_at=d.get("added_at", ""),
        )


@dataclass
class MarketplacePlugin:
    """One plugin entry inside a marketplace.json catalog."""
    name: str
    source: str = "./"               # relative source dir inside the marketplace clone
    version: str = "latest"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source, "version": self.version}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MarketplacePlugin":
        return cls(
            name=d.get("name", ""),
            source=d.get("source", d.get("url", "./")),
            version=d.get("version", "latest"),
            description=d.get("description", ""),
        )


@dataclass
class MarketplaceCatalog:
    """The parsed contents of a marketplace.json catalog."""
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    plugins: list[MarketplacePlugin] = field(default_factory=list)
    fetched_at: str = ""
    catalog_path: Path | None = None   # local file the catalog was read from
    marketplace_alias: str = ""
    root: Path | None = None           # marketplace clone root; source is relative to it

    @property
    def name(self) -> str:
        return self.raw.get("name", "") or ""

    @classmethod
    def validate(cls, raw: dict[str, Any]) -> None:
        """Validate the catalog schema; raises ValueError on bad shape."""
        if not isinstance(raw, dict):
            raise ValueError("marketplace.json must be a JSON object")
        if not isinstance(raw.get("name"), str) or not raw["name"].strip():
            raise ValueError("marketplace.json is missing a 'name'")
        plugins = raw.get("plugins") or []
        if not isinstance(plugins, list):
            raise ValueError("marketplace.json 'plugins' must be a list")
        for p in plugins:
            if not isinstance(p, dict) or not isinstance(p.get("name"), str):
                raise ValueError(
                    "marketplace.json contains a badly-shaped plugin entry"
                )

    @classmethod
    def from_raw(
        cls,
        raw: dict[str, Any],
        source_url: str = "",
        catalog_path: Path | None = None,
        marketplace_alias: str = "",
        root: Path | None = None,
    ) -> "MarketplaceCatalog":
        cls.validate(raw)
        plugins = [
            MarketplacePlugin.from_dict(p) for p in (raw.get("plugins") or [])
        ]
        return cls(
            source_url=source_url,
            raw=raw,
            plugins=plugins,
            fetched_at=datetime.now().isoformat(timespec="seconds"),
            catalog_path=catalog_path,
            marketplace_alias=marketplace_alias,
            root=root,
        )

    def search(self, name: str) -> MarketplacePlugin | None:
        """Return the plugin with the given name, or None if not present."""
        for p in self.plugins:
            if p.name == name:
                return p
        return None

    def resolve_source(self, plugin: MarketplacePlugin) -> Path:
        """Absolute source dir of a plugin inside the local marketplace clone.

        The plugin's ``source`` is relative to the marketplace clone root (the
        dir containing ``.claude-plugin/``) — so ``"./"`` means the marketplace
        root itself, matching Claude Code's ``source`` convention.
        """
        if self.root is not None:
            base = self.root
        elif self.catalog_path is not None:
            base = self.catalog_path.parent
        else:
            base = Path(self.source_url)
        src = (plugin.source or "./").strip() or "./"
        return Path(base).resolve() / src


# ── URL resolution helpers ────────────────────────────────────────────────

def _alias_from_source(source: str) -> str:
    """Derive a sensible alias from a GitHub shorthand or a repo URL."""
    m = _GITHUB_RE.match(source.strip())
    if m:
        return m.group(2)
    parts = [s for s in source.strip("/").split("/") if s]
    return parts[-1] or "marketplace"


def _github_url(source: str) -> str | None:
    """Return canonical https://github.com/owner/repo if source is a repo."""
    m = _GITHUB_RE.match(source.strip())
    if m:
        owner, repo = m.groups()
        return f"https://github.com/{owner}/{repo}"
    return None


def _sanitize(name: str) -> str:
    """Lowercase and keep only [a-z0-9._-] — safe for a folder name."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", name).strip(".-").lower()


def _discover_catalog(root: Path) -> Path | None:
    """Return the first catalog file found under ``root``, or None."""
    for rel in _CATALOG_CANDIDATES:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


# ── Public registry API ───────────────────────────────────────────────────

class MarketplaceRegistry:
    """Reads/writes the ``marketplaces`` section of the plugin state file."""

    def list(self) -> list[MarketplaceRecord]:
        state = load_state()
        return [
            MarketplaceRecord.from_dict(d)
            for d in state.get("marketplaces", {}).values()
        ]

    def lookup(self, alias: str) -> MarketplaceRecord | None:
        state = load_state()
        d = state.get("marketplaces", {}).get(alias)
        return MarketplaceRecord.from_dict(d) if d else None

    def add(self, source: str, alias: str | None = None) -> MarketplaceRecord:
        """Register a marketplace by cloning its repo and validating its catalog.

        The whole repo is cloned into ``marketplaces/<name>/``, where ``name``
        is the marketplace's own ``name`` from its ``marketplace.json`` catalog
        (or an explicit ``--alias``), per Claude Code convention. Installs then
        scan the local clone and resolve each plugin's ``source`` relative to it.
        Direct ``marketplace.json`` URLs are downloaded and cached the same way.
        """
        src = source.strip()
        repo_url = _github_url(src)
        guess = _sanitize(alias or _alias_from_source(src)) or "marketplace"
        staging = marketplaces_dir() / f".pending-{guess}"
        raw: dict | None = None
        try:
            if repo_url:
                downloader.git_clone(repo_url, staging, timeout=120)
                catalog_path = _discover_catalog(staging)
                if catalog_path is None:
                    raise ValueError(
                        f"Cloned marketplace '{src}' has no catalog "
                        "(expected .claude-plugin/marketplace.json)"
                    )
                try:
                    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Marketplace catalog is not readable JSON: {exc}"
                    ) from exc
            else:
                if not src.endswith(".json"):
                    raise ValueError(
                        "Unsupported marketplace source. Use a GitHub repo "
                        "(owner/repo or https://github.com/...) or a direct "
                        "marketplace.json URL."
                    )
                try:
                    raw = json.loads(downloader.fetch_text(src, timeout=10))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Marketplace manifest is not valid JSON: {exc}"
                    ) from exc

            # Name the folder by the catalog's own name (or --alias).
            MarketplaceCatalog.validate(raw)
            final_alias = _sanitize(alias or raw["name"]) or guess

            state = load_state()
            if final_alias in state.get("marketplaces", {}):
                raise ValueError(
                    f"Marketplace '{final_alias}' is already registered. "
                    f"Run `harness plugin marketplace remove {final_alias}` first."
                )

            dest = marketplaces_dir() / final_alias
            if repo_url:
                shutil.rmtree(dest, ignore_errors=True)  # orphaned leftover, if any
                dest.parent.mkdir(parents=True, exist_ok=True)
                staging.replace(dest)
                catalog_path = dest / catalog_path.relative_to(staging)
            else:
                dest.mkdir(parents=True, exist_ok=True)
                catalog_path = dest / "marketplace.json"
                catalog_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

            catalog = MarketplaceCatalog.from_raw(
                raw,
                source_url=src,
                catalog_path=catalog_path,
                marketplace_alias=final_alias,
                root=dest,
            )

            record = MarketplaceRecord(
                name=final_alias,
                url=src,
                path=str(dest),
                catalog=(
                    catalog_path.relative_to(dest).as_posix()
                    if catalog_path.parent != dest
                    else "marketplace.json"
                ),
                added_at=datetime.now().isoformat(timespec="seconds"),
            )

            def _add(state):
                state["marketplaces"][final_alias] = record.to_dict()
                return state

            update_state(_add)
            return record
        finally:
            # staging is moved (or never created) on success; removed on failure.
            shutil.rmtree(staging, ignore_errors=True)

    def remove(self, alias: str) -> bool:
        """Unalias a marketplace. Returns False if not registered."""
        state = load_state()
        if alias not in state.get("marketplaces", {}):
            return False
        del state["marketplaces"][alias]
        save_state(state)
        return True


def fetch_catalog(alias: str) -> MarketplaceCatalog | None:
    """Return the validated catalog for a registered marketplace alias.

    Reads from the marketplace's local clone — no network — matching the
    Claude Code convention that marketplaces are cloned locally.
    """
    record = MarketplaceRegistry().lookup(alias)
    if not record:
        return None
    path = record.catalog_path
    if not path or not path.is_file():
        if not record.path:
            raise ValueError(
                f"Marketplace '{alias}' is not registered. "
                "Run `harness plugin marketplace add <url-or-repo>` first."
            )
        raise ValueError(f"Marketplace '{alias}' clone is missing its catalog file")
    try:
        body = path.read_text(encoding="utf-8")
        raw = json.loads(body)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Marketplace '{alias}' catalog is unreadable: {exc}") from exc
    return MarketplaceCatalog.from_raw(
        raw,
        source_url=record.url,
        catalog_path=path,
        marketplace_alias=alias,
        root=Path(record.path) if record.path else None,
    )