from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, QEvent, Qt, QPoint
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QWidget,
    QAbstractButton,
    QComboBox,
    QMenu,
    QTabBar,
    QTabWidget,
    QToolButton,
    QTreeWidget,
)


_HAND_CURSOR_PROPERTY = "_ww_hand_cursor_applied"
_ORIGINAL_CURSOR_PROPERTY = "_ww_original_cursor_shape"
_FORCE_HAND_PROPERTY = "wwForceHandCursor"
_PREVENT_HAND_PROPERTY = "wwPreventHandCursor"
_CLICKABLE_PROPERTY = "wwClickableHandCursor"
_TREE_HELPER_ATTR = "_ww_tree_cursor_helper"
_MENU_HELPER_ATTR = "_ww_menu_cursor_helper"
_COMBO_HELPER_ATTR = "_ww_combo_cursor_helper"


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
            # Auto-install menu helper when a menu is shown
            if isinstance(watched, QMenu) and etype == QEvent.Show:
                enable_menu_hand_cursor(watched)
            # Auto-install combo popup helper when a combo is shown
            if isinstance(watched, QComboBox) and etype == QEvent.Show:
                enable_combo_popup_hand_cursor(watched)
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
        if isinstance(widget, QTabBar):
            return True
        if isinstance(widget, QAbstractButton):
            return True
        return False

    def _apply_hand_cursor(self, widget: QWidget) -> None:
        if widget.property(_HAND_CURSOR_PROPERTY):
            return
        # Store whether widget had a cursor set before we change it
        had_cursor = widget.testAttribute(Qt.WA_SetCursor)
        if had_cursor:
            widget.setProperty(_ORIGINAL_CURSOR_PROPERTY, widget.cursor())
        else:
            widget.setProperty(_ORIGINAL_CURSOR_PROPERTY, None)
        widget.setCursor(Qt.PointingHandCursor)
        widget.setProperty(_HAND_CURSOR_PROPERTY, True)

    def _restore_cursor(self, widget: QWidget) -> None:
        if not widget.property(_HAND_CURSOR_PROPERTY):
            return
        # Check if we saved an original cursor
        original_cursor = widget.property(_ORIGINAL_CURSOR_PROPERTY)
        if isinstance(original_cursor, QCursor):
            widget.setCursor(original_cursor)
        elif isinstance(original_cursor, int):
            widget.setCursor(QCursor(Qt.CursorShape(original_cursor)))
        elif isinstance(original_cursor, Qt.CursorShape):
            widget.setCursor(QCursor(original_cursor))
        elif original_cursor:
            try:
                widget.setCursor(QCursor(int(original_cursor)))
            except (TypeError, ValueError):
                widget.unsetCursor()
        else:
            # Widget didn't have a cursor before, so unset it
            widget.unsetCursor()
        widget.setProperty(_HAND_CURSOR_PROPERTY, False)
        widget.setProperty(_ORIGINAL_CURSOR_PROPERTY, None)

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


class _TreeCursorHelper(QObject):
    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)
        self._tree = tree
        self._viewport = tree.viewport()
        if hasattr(self._viewport, "setAttribute"):
            self._viewport.setAttribute(Qt.WA_Hover, True)
        if hasattr(self._viewport, "setMouseTracking"):
            self._viewport.setMouseTracking(True)
        self._viewport.installEventFilter(self)
        tree.destroyed.connect(self._on_tree_destroyed)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._viewport:
            etype = event.type()
            if etype in (QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
                pos = _event_pos(event)
                is_clickable = pos is not None and self._tree.itemAt(pos) is not None
                set_dynamic_clickable(self._viewport, is_clickable)
            elif etype == QEvent.HoverLeave:
                set_dynamic_clickable(self._viewport, False)
        return super().eventFilter(obj, event)

    def _on_tree_destroyed(self) -> None:
        set_dynamic_clickable(self._viewport, False)
        if hasattr(self._viewport, "removeEventFilter"):
            try:
                self._viewport.removeEventFilter(self)
            except RuntimeError:
                pass


def _event_pos(event: QEvent) -> Optional[QPoint]:
    getter = getattr(event, "pos", None)
    if getter is None:
        return None
    pos = getter()
    if hasattr(pos, "toPoint"):
        return pos.toPoint()
    return pos  # type: ignore[return-value]


def enable_tree_hand_cursor(tree: QTreeWidget) -> None:
    if getattr(tree, _TREE_HELPER_ATTR, None) is not None:
        return
    helper = _TreeCursorHelper(tree)
    setattr(tree, _TREE_HELPER_ATTR, helper)


class _MenuCursorHelper(QObject):
    """Monitors QMenu's activeAction to show hand cursor only over highlighted items."""
    
    def __init__(self, menu: QMenu) -> None:
        super().__init__(menu)
        self._menu = menu
        self._last_active_action = None
        
        # Enable hover events and mouse tracking
        if hasattr(menu, "setAttribute"):
            menu.setAttribute(Qt.WA_Hover, True)
        if hasattr(menu, "setMouseTracking"):
            menu.setMouseTracking(True)
        
        # Install event filter to monitor hover and action changes
        menu.installEventFilter(self)
        menu.hovered.connect(self._on_action_hovered)
        menu.destroyed.connect(self._on_menu_destroyed)
        
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._menu:
            etype = event.type()
            if etype in (QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
                self._update_cursor_for_active_action()
            elif etype in (QEvent.HoverLeave, QEvent.Leave):
                set_dynamic_clickable(self._menu, False)
                self._last_active_action = None
        return super().eventFilter(obj, event)
    
    def _on_action_hovered(self, action) -> None:
        """Called when an action is hovered/highlighted."""
        self._update_cursor_for_active_action()
    
    def _update_cursor_for_active_action(self) -> None:
        """Update cursor based on whether an actionable item is highlighted."""
        active_action = self._menu.activeAction()
        
        # Only update if the active action changed
        if active_action == self._last_active_action:
            return
        
        self._last_active_action = active_action
        
        # Check if the active action is clickable
        is_clickable = False
        if active_action is not None:
            # Exclude separators and disabled actions
            if not active_action.isSeparator() and active_action.isEnabled():
                is_clickable = True
        
        set_dynamic_clickable(self._menu, is_clickable)
    
    def _on_menu_destroyed(self) -> None:
        """Clean up when menu is destroyed."""
        menu = self._menu
        if menu is None:
            return
        try:
            set_dynamic_clickable(menu, False)
        except RuntimeError:
            pass
        if hasattr(menu, "removeEventFilter"):
            try:
                menu.removeEventFilter(self)
            except RuntimeError:
                pass
        self._menu = None


def enable_menu_hand_cursor(menu: QMenu) -> None:
    """Enable smart cursor behavior for a QMenu instance."""
    if getattr(menu, _MENU_HELPER_ATTR, None) is not None:
        return
    helper = _MenuCursorHelper(menu)
    setattr(menu, _MENU_HELPER_ATTR, helper)


class _ComboPopupHelper(QObject):
    """Monitors a QComboBox's popup view so hovered items show a hand cursor."""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo
        # Some combos may not have a view yet; guard
        try:
            view = combo.view()
        except Exception:
            view = None
        self._view = view
        if self._view is None:
            return
        if hasattr(self._view, "setAttribute"):
            self._view.setAttribute(Qt.WA_Hover, True)
        if hasattr(self._view, "setMouseTracking"):
            self._view.setMouseTracking(True)
        self._view.installEventFilter(self)
        self._view.destroyed.connect(self._on_view_destroyed)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._view:
            etype = event.type()
            if etype in (QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
                getter = getattr(event, "pos", None)
                if getter is not None:
                    pos = getter()
                    if hasattr(pos, "toPoint"):
                        pos = pos.toPoint()
                    is_clickable = self._view.indexAt(pos).isValid() if pos is not None else False
                    set_dynamic_clickable(self._view, bool(is_clickable))
            elif etype == QEvent.HoverLeave:
                set_dynamic_clickable(self._view, False)
        return super().eventFilter(obj, event)

    def _on_view_destroyed(self) -> None:
        try:
            set_dynamic_clickable(self._view, False)
        except RuntimeError:
            pass
        if hasattr(self._view, "removeEventFilter"):
            try:
                self._view.removeEventFilter(self)
            except RuntimeError:
                pass
        self._view = None


def enable_combo_popup_hand_cursor(combo: QComboBox) -> None:
    """Install helper for a QComboBox so its popup items show hand cursor."""
    if getattr(combo, _COMBO_HELPER_ATTR, None) is not None:
        return
    helper = _ComboPopupHelper(combo)
    setattr(combo, _COMBO_HELPER_ATTR, helper)
