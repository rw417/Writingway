from __future__ import annotations

from PyQt5.QtCore import QObject, QEvent, Qt
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

            # If the scaled delta is zero, then consume the event to prevent any line-based jump
            if dx == 0 and dy == 0:
                return True

            # Create a new wheel event with the scaled pixel delta and post it to the object
            new_event = QWheelEvent(
                event.posF(),
                event.globalPosF(),
                # pixelDelta
                event.pixelDelta().toPoint() if not event.pixelDelta().isNull() else event.pixelDelta(),
                # angleDelta scaled down
                event.angleDelta(),
                int(event.delta() * self.scale) if hasattr(event, 'delta') else 0,
                event.orientation(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
            )

            # Post the event directly to the object (deliver synchronously)
            QApplication = None
            try:
                # Avoid importing at module level to keep dependency light
                from PyQt5.QtWidgets import QApplication
                QApplication.sendEvent(obj, new_event)
            except Exception:
                # If anything goes wrong, consume the original event to avoid a large jump
                return True

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
