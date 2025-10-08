from typing import Optional

try:
    import sip  # type: ignore[import]
except Exception:
    sip = None

from PyQt5.QtWidgets import QTreeWidgetItem


def is_item_valid(item: Optional[QTreeWidgetItem]) -> bool:
    """Return True if the QTreeWidgetItem wrapper is valid (wasn't deleted by Qt).

    This wraps sip.isdeleted when available and falls back to a conservative True when sip isn't
    present (e.g., headless tests).
    """
    if item is None:
        return False
    if sip is None:
        return True
    try:
        return not sip.isdeleted(item)
    except RuntimeError:
        return False
