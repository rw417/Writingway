from __future__ import annotations

from PyQt5.QtCore import QObject, QEvent, Qt, QPoint
from PyQt5.QtGui import QWheelEvent


class _WheelFilter(QObject):
    """Event filter that normalizes wheel events to a gentler, pixel-based scroll.

    It reduces the scroll delta (slows scrolling) and ignores line-based
    scrolling (Delta in lines) by converting to a controlled pixel delta.
    """

    def __init__(self, scale: float = 0.25, parent=None):
        super().__init__(parent)
        # scale reduces the effective scroll amount; <1 slows down
        self.scale = float(scale)

    def eventFilter(self, obj, event):
        # Only intercept wheel events
        if event.type() == QEvent.Wheel and isinstance(event, QWheelEvent):
            # Prefer pixelDelta when available (touchpads), otherwise use angleDelta
            pixel = event.pixelDelta()
            angle = event.angleDelta()

            # Qt wheel angleDelta is in eights of a degree. 120 units typically == 1 line.
            # We'll convert to a controlled pixel value and create a new synthetic event
            dx = 0
            dy = 0
            if not pixel.isNull():
                dx = int(pixel.x() * self.scale)
                dy = int(pixel.y() * self.scale)
            else:
                # Convert angleDelta to approximate pixels: 120 units ~= 1 line ~= 20 pixels
                # We'll use a smaller multiplier and scale to make scrolling slower.
                dx = int(angle.x() / 120 * 8 * self.scale)
                dy = int(angle.y() / 120 * 8 * self.scale)

            # If no scaling requested, let the event be handled normally.
            if self.scale == 1.0:
                return False

            # If the scaled delta is zero, do not intercept — allow default handling.
            if dx == 0 and dy == 0:
                return False

            # Try to scroll the target widget (or its ancestors) directly by adjusting scrollbars.
            # Prefer simple, explicit operations and only catch narrow exceptions where needed.

            # Scaled deltas already computed as dx, dy above. Prefer vertical scrolling (dy).
            def try_adjust_scroll(widget, dx_val, dy_val, max_ancestors=6):
                w = widget
                # Walk up the parent chain to find a widget with scrollbars (QAbstractScrollArea)
                for _ in range(max_ancestors):
                    if w is None:
                        break
                    # Some widgets expose verticalScrollBar()/horizontalScrollBar()
                    vbar = getattr(w, "verticalScrollBar", None)
                    hbar = getattr(w, "horizontalScrollBar", None)

                    if callable(vbar):
                        sb = vbar()
                        if sb is not None and hasattr(sb, "setValue"):
                            # Subtract dy so positive wheel moves content downwards
                            sb.setValue(sb.value() - dy_val)
                            return True

                    if callable(hbar) and dx_val:
                        sbh = hbar()
                        if sbh is not None and hasattr(sbh, "setValue"):
                            sbh.setValue(sbh.value() - dx_val)
                            return True

                    # move to parent widget; parent() is expected on QWidget-like objects
                    parent = getattr(w, "parent", None)
                    if callable(parent):
                        w = parent()
                    else:
                        break

                return False

            scrolled = try_adjust_scroll(obj, dx, dy)
            if scrolled:
                # We adjusted a scrollbar directly; event handled.
                return True

            # If we couldn't find a scrollbar to adjust, fall back to sending a synthetic event
            # while temporarily removing this filter to avoid re-entry into eventFilter.
            from PyQt5.QtWidgets import QApplication

            pixel = event.pixelDelta()
            angle = event.angleDelta()

            if not pixel.isNull():
                pixel_point = QPoint(int(pixel.x() * self.scale), int(pixel.y() * self.scale))
                angle_point = QPoint(0, 0)
            else:
                pixel_point = QPoint(0, 0)
                angle_point = QPoint(
                    int(angle.x() / 120 * 8 * self.scale),
                    int(angle.y() / 120 * 8 * self.scale),
                )

            # If the scaled delta is zero, do not intercept — allow default handling.
            if pixel_point == QPoint(0, 0) and angle_point == QPoint(0, 0):
                return False

            # Try to construct a QWheelEvent using the newer signature; if it fails, send original event.
            try:
                new_event = QWheelEvent(
                    event.posF(),
                    event.globalPosF(),
                    pixel_point,
                    angle_point,
                    event.buttons(),
                    event.modifiers(),
                    event.phase(),
                    event.inverted(),
                )
            except Exception:
                # Fall back to attempting to send the original event unchanged
                new_event = event

            # First, try to call the widget's wheelEvent directly (does not go through eventFilter)
            handler = getattr(obj, "wheelEvent", None)
            if callable(handler):
                try:
                    handler(new_event)
                    return True
                except Exception:
                    # If direct call fails, continue to try child or sendEvent fallback
                    pass

            # If the widget has a child at the event position, try delivering to it
            child = None
            if hasattr(obj, "childAt"):
                pos = event.pos()
                if hasattr(pos, "toPoint"):
                    pos = pos.toPoint()
                try:
                    child = obj.childAt(pos)
                except Exception:
                    child = None

            if child and child is not obj:
                child_handler = getattr(child, "wheelEvent", None)
                if callable(child_handler):
                    try:
                        child_handler(new_event)
                        return True
                    except Exception:
                        pass

            # Fallback: temporarily remove this filter to avoid re-entry, send event, then restore.
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
                try:
                    app.sendEvent(obj, new_event)
                finally:
                    app.installEventFilter(self)
            else:
                QApplication.sendEvent(obj, new_event)

            return True

        return super().eventFilter(obj, event)


_filter_instance = None


def install_scroll_manager(app, *, scale: float = 0.25):
    """Install the global wheel-event filter on the QApplication.

    Args:
        app: QApplication instance
        scale: float multiplier to control scroll speed (0.0-1.0 recommended)
    """
    global _filter_instance
    if _filter_instance is not None:
        return
    _filter_instance = _WheelFilter(scale)
    app.installEventFilter(_filter_instance)


def uninstall_scroll_manager(app):
    global _filter_instance
    if _filter_instance is None:
        return
    try:
        app.removeEventFilter(_filter_instance)
    except Exception:
        pass
    _filter_instance = None
