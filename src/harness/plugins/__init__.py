"""Plugin marketplace support — install/uninstall bundles of agents, skills, and MCP servers."""

from .installer import PluginInstaller
from .models import PluginManifest, InstalledPlugin

__all__ = ["PluginInstaller", "PluginManifest", "InstalledPlugin"]
