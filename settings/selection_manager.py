import json
import os
import re
from typing import Dict
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt5.QtCore import Qt
from .settings_manager import WWSettingsManager

class SelectionManager:
    """Manages persistence of checkbox selections for a QTreeWidget instance in a project, scoped by panel."""

    def __init__(self, project_name: str, panel_id: str, selection_file_name: str = "selections.json"):
        """
        Initialize with the project name, panel identifier, and optional selection file name.

        Args:
            project_name (str): The name of the project.
            panel_id (str): Identifier for the panel (e.g., 'project', 'workshop').
            selection_file_name (str): Name of the file to store selections (default: selections.json).
        """
        self._panel_id = panel_id
        self.selection_file = WWSettingsManager.get_project_relpath(project_name, selection_file_name)

    def load_selections(self) -> Dict[str, bool]:
        """
        Load saved checkbox selections for the panel specified at initialization.

        Returns:
            Dict[str, bool]: Dictionary mapping item paths to their check states for the panel.
        """
        if os.path.exists(self.selection_file):
            try:
                with open(self.selection_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                panel_data = data.get("panels", {}).get(self._panel_id, {"selections": []})
                return {item["path"]: item["checked"] for item in panel_data.get("selections", [])}
            except Exception as e:
                print(f"Error loading selections from {self.selection_file}: {e}")
        return {}

    def save_selections(self, tree: QTreeWidget) -> None:
        """
        Traverse the QTreeWidget and save the check states of checkable items for the panel specified at initialization.

        Args:
            tree (QTreeWidget): The tree widget to traverse for selections.
        """
        selections = []
        def traverse_item(item: QTreeWidgetItem, parent_path: str = ""):
            item_text = item.text(0)
            current_path = f"{parent_path}/{item_text}" if parent_path else item_text
            if item.flags() & Qt.ItemIsUserCheckable:
                selections.append({
                    "path": current_path,
                    "checked": item.checkState(0) == Qt.Checked
                })
            for i in range(item.childCount()):
                traverse_item(item.child(i), current_path)

        root = tree.invisibleRootItem()
        for i in range(root.childCount()):
            traverse_item(root.child(i))

        # Load existing data to preserve other panels' selections
        try:
            if os.path.exists(self.selection_file):
                with open(self.selection_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
        except Exception as e:
            print(f"Error reading existing selections from {self.selection_file}: {e}")
            data = {}

        # Ensure 'panels' key exists
        if "panels" not in data:
            data["panels"] = {}
        # Update selections for the specified panel
        data["panels"][self._panel_id] = {"selections": selections}

        # Save updated data
        try:
            with open(self.selection_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving selections to {self.selection_file}: {e}")

    def is_checked(self, path: str) -> bool:
        """
        Check if an item with the given path is checked for the panel specified at initialization.

        Args:
            path (str): The path identifying the item (e.g., 'Category/Entry').

        Returns:
            bool: True if the item is checked, False otherwise.
        """
        selections = self.load_selections()
        return selections.get(path, False)