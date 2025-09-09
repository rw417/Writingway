from PyQt5.QtWidgets import QWidget, QTreeWidget, QVBoxLayout, QMenu, QTreeWidgetItem, QMessageBox, QDialog
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QBrush
import json, os, re, uuid
from langchain.prompts import PromptTemplate

from .ai_compendium_dialog import AICompendiumDialog
from settings.llm_api_aggregator import WWApiAggregator
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager
from settings.llm_settings_dialog import LLMSettingsDialog

DEBUG = False  # Set to True to enable debug prints

def sanitize(text):
    return re.sub(r'\W+', '', text)

class CompendiumPanel(QWidget):
    compendium_updated = pyqtSignal(str)  # str is the project_name

    def __init__(self, parent=None, enhanced_window=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.project_window = parent
        self.enhanced_window = enhanced_window  # Store enhanced_window instance
        self.project_name = getattr(self.parent().model, "project_name", "default")
        self.new_compendium_file = os.path.join(os.getcwd(), "Projects", sanitize(self.project_name), "compendium.json")
        if DEBUG:
            print("New compendium file path:", self.new_compendium_file)
        
        project_dir = os.path.dirname(self.new_compendium_file)
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)
        
        self.old_compendium_file = os.path.join(os.getcwd(), "compendium.json")
        if os.path.exists(self.old_compendium_file):
            if DEBUG:
                print("Old compendium file found at", self.old_compendium_file)
            try:
                with open(self.old_compendium_file, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                with open(self.new_compendium_file, "w", encoding="utf-8") as f:
                    json.dump(old_data, f, indent=2)
                os.remove(self.old_compendium_file)
                if DEBUG:
                    print("Migrated compendium data to", self.new_compendium_file)
            except Exception as e:
                if DEBUG:
                    print("Error migrating old compendium file:", e)
        
        self.compendium_file = self.new_compendium_file
        self.connect_to_compendium_signal()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel(_("Compendium"))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree.currentItemChanged.connect(self.on_item_changed)
        
        layout.addWidget(self.tree)
        
        self.populate_compendium()

    def populate_compendium(self):
        selected_item_info = self.get_selected_item_info()
        self.tree.clear()
        bold_font = QFont()
        bold_font.setBold(True)
        if os.path.exists(self.compendium_file):
            try:
                with open(self.compendium_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if DEBUG:
                    print("Compendium data loaded:", data)
                
                # Migrate to add uuid if missing
                changed = False
                for cat in data.get("categories", []):
                    for entry in cat.get("entries", []):
                        if "uuid" not in entry:
                            entry["uuid"] = str(uuid.uuid4())
                            changed = True
                if changed:
                    with open(self.compendium_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    if DEBUG:
                        print("Added UUIDs to compendium entries and saved.")
    
                if isinstance(data.get("categories"), dict):
                    if DEBUG:
                        print("Old format detected. Converting data...")
                    old_categories = data["categories"]
                    category_order = data.get("category_order", list(old_categories.keys()))
                    new_categories = []
                    for cat_name in category_order:
                        entries_dict = old_categories.get(cat_name, {})
                        entries_list = []
                        for entry_name, entry_content in entries_dict.items():
                            entries_list.append({
                                "name": entry_name,
                                "content": entry_content
                            })
                        new_categories.append({
                            "name": cat_name,
                            "entries": entries_list
                        })
                    data["categories"] = new_categories
                    with open(self.compendium_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    if DEBUG:
                        print("Conversion complete. Data saved in new format.")
                
                for cat in data.get("categories", []):
                    cat_item = QTreeWidgetItem(self.tree, [cat.get("name", "Unnamed Category")])
                    cat_item.setData(0, Qt.UserRole, "category")
                    # Mark as category for stylesheet
                    cat_item.setData(0, Qt.ItemDataRole.UserRole + 1, "true")  # Custom property for is-category
                    # Set background color from ThemeManager
                    cat_item.setBackground(0, QBrush(ThemeManager.get_category_background_color()))
                    cat_item.setFont(0, bold_font)  # Apply bold font
                    for entry in cat.get("entries", []):
                        entry_item = QTreeWidgetItem(cat_item, [entry.get("name", "Unnamed Entry")])
                        entry_item.setData(0, Qt.UserRole, "entry")
                        entry_item.setData(1, Qt.UserRole, entry.get("content", ""))
                    cat_item.setExpanded(True)
            except Exception as e:
                if DEBUG:
                    print("Error loading compendium data:", e)
        else:
            if DEBUG:
                print("Compendium file not found at", self.compendium_file)
            default_data = {"categories": [{"name": "Characters", "entries": [{"name": "Readme", "content": "This is a dummy entry. You can view it for reference."}]}]}
            try:
                with open(self.compendium_file, "w", encoding="utf-8") as f:
                    json.dump(default_data, f, indent=2)
                if DEBUG:
                    print("Created default compendium data at", self.compendium_file)
            except Exception as e:
                if DEBUG:
                    print("Error creating default compendium file:", e)
            self.populate_compendium()
        self.restore_selection(selected_item_info)

    def get_selected_item_info(self):
        current_item = self.tree.currentItem()
        if not current_item:
            return None
        item_type = current_item.data(0, Qt.UserRole)
        item_name = current_item.text(0)
        if item_type == "entry":
            parent_item = current_item.parent()
            parent_name = parent_item.text(0) if parent_item else None
            return {"type": "entry", "name": item_name, "category": parent_name}
        return {"type": "category", "name": item_name}

    def restore_selection(self, selected_item_info):
        if not selected_item_info:
            return
        item_type = selected_item_info["type"]
        item_name = selected_item_info["name"]
        if item_type == "category":
            for i in range(self.tree.topLevelItemCount()):
                cat_item = self.tree.topLevelItem(i)
                if cat_item.text(0) == item_name and cat_item.data(0, Qt.UserRole) == "category":
                    self.tree.setCurrentItem(cat_item)
                    return
        elif item_type == "entry":
            category_name = selected_item_info["category"]
            for i in range(self.tree.topLevelItemCount()):
                cat_item = self.tree.topLevelItem(i)
                if category_name and cat_item.text(0) != category_name:
                    continue
                for j in range(cat_item.childCount()):
                    entry_item = cat_item.child(j)
                    if entry_item.text(0) == item_name and entry_item.data(0, Qt.UserRole) == "entry":
                        self.tree.setCurrentItem(entry_item)
                        return
            if category_name:
                for i in range(self.tree.topLevelItemCount()):
                    cat_item = self.tree.topLevelItem(i)
                    if cat_item.text(0) == category_name:
                        if cat_item.childCount() > 0:
                            self.tree.setCurrentItem(cat_item.child(0))
                        else:
                            self.tree.setCurrentItem(cat_item)
                        return
        self.tree.clearSelection()

    def on_item_changed(self, current, previous):
        """Display entry content in the main editor."""
        main_editor = self.project_window.compendium_editor
        if current is None:
            main_editor.clear()
            return
        if current.data(0, Qt.UserRole) == "entry":
            content = current.data(1, Qt.UserRole)
            main_editor.setPlainText(content)
        else:
            main_editor.clear()

    def show_tree_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        action_open = menu.addAction(_("Open Enhanced Compendium"))
        action_analyze = menu.addAction(_("Analyze Scene with AI"))
        action = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if action == action_open:
            self.open_in_enhanced_compendium()
        elif action == action_analyze:
            self.analyze_scene_with_ai()

    def open_in_enhanced_compendium(self):
        if not self.enhanced_window:
            QMessageBox.warning(self, _("Error"), _("Enhanced Compendium window not available."))
            return
        entry_name = None
        current_item = self.tree.currentItem()
        if current_item and current_item.data(0, Qt.UserRole) == "entry":
            entry_name = current_item.text(0)
            if entry_name.startswith("* "):
                entry_name = entry_name[2:]
        self.enhanced_window.open_with_entry(self.project_name, entry_name)

    def analyze_scene_with_ai(self):
        scene_editor = self.project_window.scene_editor.editor
        if not scene_editor or not scene_editor.toPlainText():
            QMessageBox.warning(self, _("Warning"), _("No scene content available to analyze."))
            return
        scene_content = scene_editor.toPlainText()
        current_compendium = {}
        if os.path.exists(self.compendium_file):
            try:
                with open(self.compendium_file, "r", encoding="utf-8") as f:
                    current_compendium = json.load(f)
            except Exception as e:
                print(f"Error loading compendium: {e}")
        overrides = LLMSettingsDialog.show_dialog(
            self,
            default_provider=WWSettingsManager.get_active_llm_name(),
            default_model=WWSettingsManager.get_active_llm_config().get("model", None),
            default_timeout=60
        )
        if not overrides:
            return
        analysis_template = PromptTemplate(
            input_variables=["scene_content", "existing_compendium"],
            template="""Analyze the following scene content and existing compendium data. 
Generate or update compendium entries in JSON format for:
1. Major and minor characters (name, personality, description, relationships)
2. Locations (name, description)
3. Key objects (name, description)
4. Significant plot items (name, description)
Compendium entries apply to the entire story, so do not update existing entries for current status.
Scene Content:
{scene_content}
Existing Compendium:
{existing_compendium}
Return only the JSON result without additional commentary. The JSON should maintain the structure:
{{
  "categories": [
    {{
      "name": "category_name",
      "entries": [
        {{
          "name": "entry_name",
          "content": "description and details",
          "relationships": [{{"name": "related_entry", "type": "relationship_type"}}] (optional)
        }}
      ]
    }}
  ]
}}
"""
        )
        prompt = analysis_template.format(
            scene_content=scene_content,
            existing_compendium=json.dumps(current_compendium, indent=2)
        )
        try:
            response = WWApiAggregator.send_prompt_to_llm(prompt, overrides=overrides)
            cleaned_response = self.preprocess_json_string(response)
            repaired_response = self.repair_incomplete_json(cleaned_response)
            if repaired_response is None:
                QMessageBox.warning(self, _("Error"), _("AI returned invalid JSON that could not be repaired."))
                return
            try:
                ai_compendium = json.loads(repaired_response)
            except json.JSONDecodeError:
                QMessageBox.warning(self, _("Error"), _("AI returned invalid JSON format."))
                return
            dialog = AICompendiumDialog(ai_compendium, self.compendium_file, self)
            if dialog.exec_() == QDialog.Accepted:
                self.save_ai_analysis(dialog.get_compendium_data())
        except Exception as e:
            QMessageBox.warning(self, _("Error"), _("Failed to analyze scene: {}").format(str(e)))

    def preprocess_json_string(self, raw_string):
        cleaned = re.sub(r'^```(?:json)?\s*\n', '', raw_string, flags=re.MULTILINE)
        cleaned = re.sub(r'\n```$', '', cleaned, flags=re.MULTILINE)
        return cleaned.strip()
    
    def repair_incomplete_json(self, json_str):
        try:
            json.loads(json_str)
            return json_str
        except json.JSONDecodeError:
            repaired = json_str.strip()
            if repaired.endswith('"'):
                repaired += '"'
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
            for _ in range(open_braces):
                repaired += '}'
            for _ in range(open_brackets):
                repaired += ']'
            try:
                json.loads(repaired)
                return repaired
            except json.JSONDecodeError:
                return None

    def save_ai_analysis(self, ai_compendium):
        try:
            if os.path.exists(self.compendium_file):
                with open(self.compendium_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if "extensions" not in existing:
                    existing["extensions"] = {"entries": {}}
                elif "entries" not in existing["extensions"]:
                    existing["extensions"]["entries"] = {}
                existing_categories = {cat["name"]: cat for cat in existing.get("categories", [])}
                for new_cat in ai_compendium.get("categories", []):
                    if new_cat["name"] in existing_categories:
                        existing_entries = {entry["name"]: entry for entry in existing_categories[new_cat["name"]]["entries"]}
                        for new_entry in new_cat.get("entries", []):
                            entry_name = new_entry["name"]
                            existing_entries[entry_name] = {
                                "name": entry_name,
                                "content": new_entry.get("content", ""),
                                "relationships": new_entry.get("relationships", []),
                                "uuid": new_entry.get("uuid", str(uuid.uuid4()))
                            }
                            existing["extensions"]["entries"][entry_name] = {
                                "relationships": new_entry.get("relationships", []),
                                **existing["extensions"]["entries"].get(entry_name, {})
                            }
                        existing_categories[new_cat["name"]]["entries"] = list(existing_entries.values())
                    else:
                        existing["categories"].append(new_cat)
                        for entry in new_cat.get("entries", []):
                            entry_name = entry["name"]
                            existing["extensions"]["entries"][entry_name] = {
                                "relationships": entry.get("relationships", [])
                            }
            else:
                existing = {
                    "categories": ai_compendium.get("categories", []),
                    "extensions": {
                        "entries": {
                            entry["name"]: {"relationships": entry.get("relationships", [])}
                            for cat in ai_compendium.get("categories", [])
                            for entry in cat.get("entries", [])
                        }
                    }
                }
            with open(self.compendium_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            self.populate_compendium()
            self.compendium_updated.emit(self.project_name)
            QMessageBox.information(self, _("Success"), _("Compendium updated successfully."))
        except Exception as e:
            QMessageBox.warning(self, _("Error"), _("Failed to save compendium: {}").format(str(e)))

    def connect_to_compendium_signal(self):
        if self.enhanced_window:
            self.enhanced_window.compendium_updated.connect(self.update_compendium_tree)
        
    @pyqtSlot(str)
    def update_compendium_tree(self, project_name):
        if project_name == self.project_name and self.isVisible():
            self.populate_compendium()