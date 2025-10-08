from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, QEvent, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QAbstractButton,
    QComboBox,
    QTabBar,
    QTabWidget,
    QToolButton,
)


_HAND_CURSOR_PROPERTY = "_ww_hand_cursor_applied"
_FORCE_HAND_PROPERTY = "wwForceHandCursor"
_PREVENT_HAND_PROPERTY = "wwPreventHandCursor"
_CLICKABLE_PROPERTY = "wwClickableHandCursor"


class CursorManager(QObject):
    """Global cursor handler that swaps between arrow and pointing hand cursors.

    The manager applies a pointing hand cursor whenever the mouse hovers
    above widgets considered *clickable* and reverts to the standard arrow
    cursor when the mouse leaves. Widgets can opt-in/out via the dynamic
    properties documented below.

    Dynamic properties exposed:
        - ``wwForceHandCursor``: Always show pointing hand while hovered.
        - ``wwPreventHandCursor``: Never show pointing hand cursor.
        - ``wwClickableHandCursor``: Treat widget as clickable when True.
    """

    _instance: Optional["CursorManager"] = None

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self._app.installEventFilter(self)

    @classmethod
    def install(cls, app) -> "CursorManager":
        """Install the cursor manager on the provided application."""
        if cls._instance is None:
            cls._instance = cls(app)
        return cls._instance

    def eventFilter(self, watched, event):
        if isinstance(watched, QWidget):
            etype = event.type()
            if etype in (QEvent.Enter, QEvent.HoverEnter, QEvent.HoverMove):
                self._handle_hover(watched)
            elif etype in (QEvent.Leave, QEvent.HoverLeave):
                self._restore_cursor(watched)
            elif etype == QEvent.EnabledChange and not watched.isEnabled():
                # Ensure disabled widgets revert to their default cursor
                self._restore_cursor(watched)
        return super().eventFilter(watched, event)

    def _handle_hover(self, widget: QWidget) -> None:
        if self._should_use_hand_cursor(widget):
            self._apply_hand_cursor(widget)
        else:
            # In case a child widget inherits a property from a parent that we
            # previously modified, ensure it stays at the default arrow cursor.
            self._restore_cursor(widget)

    def _should_use_hand_cursor(self, widget: QWidget) -> bool:
        if widget.property(_PREVENT_HAND_PROPERTY):
            return False
        if widget.property(_FORCE_HAND_PROPERTY):
            return True
        if not widget.isEnabled():
            return False
        if isinstance(widget, QComboBox):
            return True
        if widget.property(_CLICKABLE_PROPERTY):
            return True
        if isinstance(widget, QTabWidget):
            return True
        if isinstance(widget, QTabBar):
            return True
        if isinstance(widget, QAbstractButton):
            return True
        return False

    def _apply_hand_cursor(self, widget: QWidget) -> None:
        if widget.property(_HAND_CURSOR_PROPERTY):
            return
        widget.setCursor(Qt.PointingHandCursor)
        widget.setProperty(_HAND_CURSOR_PROPERTY, True)

    def _restore_cursor(self, widget: QWidget) -> None:
        if widget.property(_HAND_CURSOR_PROPERTY):
            widget.unsetCursor()
            widget.setProperty(_HAND_CURSOR_PROPERTY, False)

    def set_widget_clickable(self, widget: QWidget, is_clickable: bool) -> None:
        widget.setProperty(_CLICKABLE_PROPERTY, bool(is_clickable))
        if is_clickable:
            self._apply_hand_cursor(widget)
        else:
            self._restore_cursor(widget)


def install_cursor_manager(app) -> CursorManager:
    """Convenience helper mirroring :meth:`CursorManager.install`."""
    return CursorManager.install(app)


def set_dynamic_clickable(widget: QWidget, is_clickable: bool) -> None:
    manager = CursorManager._instance
    if manager is not None:
        manager.set_widget_clickable(widget, is_clickable)
