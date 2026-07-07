"""UI state management for terminal interface."""

from dataclasses import dataclass, field
from typing import Dict, Any
from .statusbar import StatusInfo
from .main_panel import MainPanelState
from .input_bar import InputBarState


@dataclass
class UIState:
    """Central state for terminal UI."""
    status: StatusInfo = field(default_factory=StatusInfo)
    main_panel: MainPanelState = field(default_factory=MainPanelState)
    input_bar: InputBarState = field(default_factory=InputBarState)
    active_pane: str = "input"
    is_running: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def pause(self) -> None:
        """Pause execution."""
        self.status.status = "paused"
        self.is_running = False

    def resume(self) -> None:
        """Resume execution."""
        self.status.status = "executing"
        self.is_running = True

    def error(self, message: str) -> None:
        """Set error state."""
        self.status.status = "error"

    def ready(self) -> None:
        """Set ready state."""
        self.status.status = "ready"

    def shutdown(self) -> None:
        """Shut down the UI."""
        self.is_running = False
