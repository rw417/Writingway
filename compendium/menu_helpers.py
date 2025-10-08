from PyQt5.QtWidgets import QMenu, QAction
from PyQt5.QtCore import Qt

# translation helper (fallback)
try:
    from compendium.enhanced_compendium import _
except Exception:
    def _(s):
        return s

# Small helpers to build context menus for the compendium window.
# These helpers only build and return the menu or action objects; they do
# not perform the actual operations. This keeps UI building separate from
# business logic in enhanced_compendium.

def build_tree_menu(window, item):
    """Return a QMenu configured for the given tree item (or None if no item).

    Usage: action = menu.exec_(window.tree.viewport().mapToGlobal(pos))
    """
    menu = QMenu(window)
    try:
        from compendium.enhanced_compendium import _
    except Exception:
        def _(s):
            return s
    if item is None:
        menu.addAction(_("New Category"))
        menu.addSeparator()
        menu.addAction(_("Analyze Scene with AI"))
        return menu

    item_type = item.data(0, Qt.UserRole)
    if item_type == "category":
        menu.addAction(_("New Entry"))
        menu.addAction(_("Delete Category"))
        menu.addAction(_("Rename Category"))
        menu.addAction(_("Move Up"))
        menu.addAction(_("Move Down"))
    elif item_type == "entry":
        menu.addAction(_("Save Entry"))
        menu.addAction(_("Delete Entry"))
        menu.addAction(_("Rename Entry"))
        menu.addAction(_("Move To..."))
        menu.addAction(_("Move Up"))
        menu.addAction(_("Move Down"))
        menu.addSeparator()
        menu.addAction(_("Analyze Scene with AI"))
    return menu


def build_tags_menu(window, item):
    menu = QMenu(window)
    if item is not None:
        menu.addAction(_("Remove Tag"))
        menu.addAction(_("Move Up"))
        menu.addAction(_("Move Down"))
    return menu


def build_relationships_menu(window, item):
    menu = QMenu(window)
    if item is not None:
        menu.addAction(_("Remove Relationship"))
    return menu
