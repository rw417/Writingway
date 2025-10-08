from typing import Optional
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtCore import Qt
from settings.theme_manager import ThemeManager

class TreeController:
    def __init__(self, tree_widget: QTreeWidget, model):
        self.tree = tree_widget
        self.model = model

    def populate_tree(self):
        self.tree.clear()
        bold_font = QFont()
        bold_font.setBold(True)
        data = self.model.as_data()
        for cat in data.get("categories", []):
            cat_item = QTreeWidgetItem(self.tree, [cat.get("name", "Unnamed Category")])
            cat_item.setData(0, Qt.UserRole, "category")
            cat_item.setFont(0, bold_font)
            cat_item.setBackground(0, QBrush(ThemeManager.get_category_background_color()))
            for entry in cat.get("entries", []):
                entry_name = entry.get("name", "Unnamed Entry")
                entry_item = QTreeWidgetItem(cat_item, [entry_name])
                entry_item.setData(0, Qt.UserRole, "entry")
                entry_item.setData(1, Qt.UserRole, (entry.get("content") or {}).get("description", ""))
                entry_item.setData(2, Qt.UserRole, entry.get("uuid"))
                if entry_name in data.get("extensions", {}).get("entries", {}):
                    extended = data["extensions"]["entries"][entry_name]
                    tags = extended.get("tags", [])
                    if tags:
                        first_tag = tags[0]
                        tag_color = first_tag["color"] if isinstance(first_tag, dict) else "#000000"
                        entry_item.setForeground(0, QBrush(QColor(tag_color)))
            cat_item.setExpanded(True)

    def get_entry_item(self, entry_name: str):
        """Return the QTreeWidgetItem for entry_name, or None if not found."""
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            for j in range(cat_item.childCount()):
                entry_item = cat_item.child(j)
                if entry_item.text(0) == entry_name:
                    return entry_item
        return None

    def find_and_select_entry(self, entry_name: str):
        item = self.get_entry_item(entry_name)
        if item is not None:
            self.tree.setCurrentItem(item)
        return item

    def update_relation_combo_items(self, combo):
        combo.clear()
        data = self.model.as_data()
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            for j in range(cat_item.childCount()):
                entry_item = cat_item.child(j)
                combo.addItem(entry_item.text(0))

    def select_first_entry(self):
        return self.select_first_entry_in_tree(self.tree)

    @staticmethod
    def select_first_entry_in_tree(tree: QTreeWidget):
        for i in range(tree.topLevelItemCount()):
            cat_item = tree.topLevelItem(i)
            if cat_item.childCount() > 0:
                entry_item = cat_item.child(0)
                if entry_item.data(0, Qt.UserRole) == "entry":
                    tree.setCurrentItem(entry_item)
                    return entry_item
        return None

    def filter_tree(self, text: str, compendium_data: Optional[dict] = None):
        data = compendium_data if compendium_data is not None else self.model.as_data()
        self.filter_tree_items(self.tree, text, data)

    @staticmethod
    def filter_tree_items(tree: QTreeWidget, text: str, compendium_data: Optional[dict]):
        if not text:
            for i in range(tree.topLevelItemCount()):
                cat_item = tree.topLevelItem(i)
                cat_item.setHidden(False)
                for j in range(cat_item.childCount()):
                    cat_item.child(j).setHidden(False)
            return
        lowered = text.lower()
        extensions = (compendium_data or {}).get("extensions", {}).get("entries", {}) if compendium_data else {}
        for i in range(tree.topLevelItemCount()):
            cat_item = tree.topLevelItem(i)
            cat_visible = False
            if lowered in cat_item.text(0).lower():
                cat_visible = True
            for j in range(cat_item.childCount()):
                entry_item = cat_item.child(j)
                entry_name = entry_item.text(0)
                match = lowered in entry_name.lower()
                if not match and entry_name in extensions:
                    extended_data = extensions[entry_name]
                    for tag in extended_data.get("tags", []):
                        tag_name = tag.get("name") if isinstance(tag, dict) else tag
                        if isinstance(tag_name, str) and lowered in tag_name.lower():
                            match = True
                            break
                entry_item.setHidden(not match)
                if match:
                    cat_visible = True
            cat_item.setHidden(not cat_visible)

    def move_item(self, item: QTreeWidgetItem, direction: str) -> bool:
        return self.move_item_in_tree(self.tree, item, direction)

    @staticmethod
    def move_item_in_tree(tree: QTreeWidget, item: QTreeWidgetItem, direction: str) -> bool:
        if item is None or direction not in {"up", "down"}:
            return False
        parent = item.parent() or tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        if direction == "up" and index > 0:
            parent.takeChild(index)
            parent.insertChild(index - 1, item)
            tree.setCurrentItem(item)
            return True
        if direction == "down" and index < parent.childCount() - 1:
            parent.takeChild(index)
            parent.insertChild(index + 1, item)
            tree.setCurrentItem(item)
            return True
        return False

    def update_entry_indicator(self, entry_item: QTreeWidgetItem, entry_name: str, compendium_data: Optional[dict] = None):
        data = compendium_data if compendium_data is not None else self.model.as_data()
        self.apply_entry_indicator(entry_item, entry_name, data)

    @staticmethod
    def apply_entry_indicator(entry_item: QTreeWidgetItem, entry_name: str, compendium_data: Optional[dict]):
        if entry_item is None:
            return
        entry_item.setText(0, entry_name)
        color = QColor("black")
        extensions = (compendium_data or {}).get("extensions", {}).get("entries", {}) if compendium_data else {}
        if entry_name in extensions:
            extended_data = extensions[entry_name]
            tags = extended_data.get("tags", [])
            if tags:
                first_tag = tags[0]
                tag_color = first_tag.get("color") if isinstance(first_tag, dict) else first_tag
                if isinstance(tag_color, str):
                    color = QColor(tag_color)
        entry_item.setForeground(0, QBrush(color))
