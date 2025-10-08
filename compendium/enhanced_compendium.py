import os
import json
from util.cursor_manager import enable_tree_hand_cursor
from .compendium_model import CompendiumModel
import re
import shutil
from contextlib import suppress
from datetime import datetime
from PyQt5.QtWidgets import (QMainWindow, QWidget, QToolBar, QSplitter, QTreeWidget, QTextEdit, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QCheckBox, QComboBox, QPushButton, QListWidget, QTabWidget, QFileDialog, QMessageBox, QTreeWidgetItem,
                             QScrollArea, QFormLayout, QGroupBox, QInputDialog, QMenu, QColorDialog, QSizePolicy, QListWidgetItem, QDialog, QApplication)
from PyQt5.QtCore import Qt, pyqtSignal, QSettings, QTimer, QPoint, QRect
from PyQt5.QtGui import QPixmap, QColor, QBrush, QFont, QCursor
from PyQt5.QtCore import QEvent
import json
import os
import re
import uuid
from langchain.prompts import PromptTemplate
from .ai_integration import preprocess_json_string, repair_incomplete_json, analyze_scene_with_llm
from .tree_controller import TreeController
from .watcher import CompendiumWatcher

try:
    import sip  # type: ignore[import]
except ImportError:  # pragma: no cover - sip may not be available in headless tests
    sip = None  # type: ignore[assignment]

from .ai_compendium_dialog import AICompendiumDialog
from settings.llm_api_aggregator import WWApiAggregator
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager
from settings.llm_settings_dialog import LLMSettingsDialog
import logging

logger = logging.getLogger(__name__)
from .ui_helpers import is_item_valid

DEBUG = False

# gettext '_' fallback for static analysis / standalone edits
def _(s):
    """Translation function fallback"""
    import builtins
    return builtins._(s) if hasattr(builtins, '_') else s

#############################
# ENHANCED COMPENDIUM CLASS #
#############################
class EnhancedCompendiumWindow(QMainWindow):
    # Define a signal that includes the project name
    compendium_updated = pyqtSignal(str)
    def __init__(self, project_name="default", parent=None):
        super().__init__(parent)
        
        self.dirty = False
        self.project_name = project_name
        self.controller = parent
        self.project_window = parent  # For compatibility with AI analysis feature
        # Use CompendiumWatcher to debounce file system events
        try:
            self.file_watcher = CompendiumWatcher(self)
            self.file_watcher.set_callback(self._on_compendium_path_changed)
        except Exception:
            # fallback to None in headless or constrained environments
            self.file_watcher = None
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(250)
        self._reload_timer.timeout.connect(self._perform_compendium_reload)
        self._pending_external_reload = False

        # Set up the central widget (which holds the main layout and splitter)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.project_toolbar = self.create_toolbar()
        self.addToolBar(self.project_toolbar)
        self.populate_project_combo(self.project_name)

        # Create the main splitter for the rest of the UI
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.main_splitter)

        # Create the left (tree), center (content/tabs), and right (tags) panels
        self.create_tree_view()
        self.create_center_panel()
        self.create_right_panel()

        # Set splitter proportions
        self.main_splitter.setStretchFactor(0, 1)  # Tree view
        self.main_splitter.setStretchFactor(1, 2)  # Content panel
        self.main_splitter.setStretchFactor(2, 1)  # Right panel

        # Set up the compendium file and populate the UI
        self.setup_compendium_file()
        self.populate_compendium()
        self._reset_compendium_watchers()
        self.connect_signals()

        # Window title and size
        self.setWindowTitle(_("Enhanced Compendium - {}").format(self.project_name))
        self.resize(900, 700)

        # Read saved settings
        self.read_settings()
    
    def read_settings(self):
        """Read window and splitter settings from QSettings."""
        settings = QSettings("MyCompany", "WritingwayProject")
        geometry = settings.value("compendium_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        window_state = settings.value("compendium_windowState")
        if window_state:
            self.restoreState(window_state)
        splitter_state = settings.value("compendium_mainSplitterState")
        if splitter_state:
            self.main_splitter.restoreState(splitter_state)

    def write_settings(self):
        """Write window and splitter settings to QSettings."""
        settings = QSettings("MyCompany", "WritingwayProject")
        settings.setValue("compendium_geometry", self.saveGeometry())
        settings.setValue("compendium_windowState", self.saveState())
        settings.setValue("compendium_mainSplitterState", self.main_splitter.saveState())

    def closeEvent(self, event):
        """Handle window close event to save settings and any unsaved changes."""
        if self.dirty and hasattr(self, 'current_entry') and hasattr(self, 'current_entry_item'):
            # Consolidated save: always use save_entry(path) so editor content
            # is copied into the tree item before serializing.
            try:
                self.save_entry(self.current_entry_item)
            except Exception:
                # Fall back to previous behaviour if something goes wrong
                pass
        # remove app event filter if we installed it
        try:
            app = QApplication.instance()
            if getattr(self, '_app_filter_installed', False) and app is not None:
                with suppress(RuntimeError, TypeError):
                    app.removeEventFilter(self)
        except Exception:
            pass
        self.write_settings()
        event.accept()
        # Emit the compendium_updated signal
        self.compendium_updated.emit(self.project_name)

    def mark_dirty(self):
        self.dirty = True

    def _save_dirty_entry_if_needed(self) -> bool:
        """Persist the current entry if unsaved changes are present.

        Returns True on success (or if no save was necessary). If saving fails,
        a warning is displayed and False is returned so callers can abort the
        operation that triggered the save attempt.
        """
        if not self.dirty:
            return True
        if not hasattr(self, "current_entry") or not hasattr(self, "current_entry_item"):
            self.dirty = False
            return True
        item = self.current_entry_item
        if not self._is_item_valid(item):
            # Attempt to re-acquire the tree item by name; if it no longer
            # exists we simply clear the dirty flag and proceed.
            item = self._select_entry_by_name(self.current_entry)
            if item is None:
                self.dirty = False
                return True
            self.current_entry_item = item
        try:
            self.save_entry(item)
            return True
        except Exception as exc:
            if DEBUG:
                logger.exception("Failed to save dirty entry before operation: %s", exc)
            QMessageBox.warning(self, _("Error"), _("Failed to save current entry: {}").format(str(exc)))
            return False

    def _rebind_current_entry_item(self) -> None:
        """Refresh the cached tree item for the current entry after repopulating."""
        if hasattr(self, "current_entry"):
            item = self._select_entry_by_name(self.current_entry)
            if item is not None:
                self.current_entry_item = item
            else:
                # The entry may have been removed; clear UI state to stay in sync.
                self.clear_entry_ui()

    def _select_entry_by_name(self, entry_name: str):
        controller = getattr(self, "tree_controller", None)
        if controller:
            return controller.find_and_select_entry(entry_name)
        return TreeController.find_and_select_entry_in_tree(self.tree, entry_name)

    def _refresh_relation_combo(self):
        controller = getattr(self, "tree_controller", None)
        if controller:
            controller.update_relation_combo_items(self.rel_entry_combo)
        else:
            TreeController.populate_relation_combo_from_tree(self.tree, self.rel_entry_combo)
    
    def create_toolbar(self):
        toolbar = QToolBar(_("Project Toolbar"), self)
        toolbar.setObjectName("EnhToolBar_Main")
        label = QLabel(_("<b>Project:</b>"))
        toolbar.addWidget(label)
        self.project_combo = QComboBox()
        toolbar.addWidget(self.project_combo)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        toolbar.addWidget(spacer)
        return toolbar
    
    def populate_project_combo(self, project_name = None):
        """Populate the project pulldown with subdirectories in Projects."""
        projects_path = os.path.join(os.getcwd(), "Projects")
        if not os.path.exists(projects_path):
            os.makedirs(projects_path)
        # Get all project folders
        projects = [d for d in os.listdir(projects_path) if os.path.isdir(os.path.join(projects_path, d))]
        
        if project_name:
            self.project_name = project_name
        else:
            project_name = self.project_name

        # If there are other projects and "default" is among them, remove it.
        if projects and len(projects) > 1 and "default" in projects:
            projects.remove("default")
        
        # Block signals during update
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        
        if projects:
            projects.sort()
            self.project_combo.addItems(projects)
            # If self.project_name isn’t in the list, use the first project from the folder.
            index = self.project_combo.findText(self.sanitize(project_name))
            if index < 0:
                self.project_combo.setCurrentIndex(0)
                self.project_name = self.project_combo.currentText()
            else:
                self.project_combo.setCurrentIndex(index)
        else:
            # If there are no project folders, fall back to "default"
            self.project_combo.addItem("default")
            self.project_combo.setCurrentIndex(0)
            self.project_name = "default"
        
        self.project_combo.blockSignals(False)
        with suppress(TypeError):
            self.project_combo.currentTextChanged.disconnect(self.on_project_combo_changed)
        self.project_combo.currentTextChanged.connect(self.on_project_combo_changed)
        self.setWindowTitle(_("Enhanced Compendium - {}").format(self.project_name))
    
    def on_project_combo_changed(self, new_project):
        """Update the project and reload the compendium when a different project is selected."""
        self.change_project(new_project)
        controller = getattr(self, 'tree_controller', None)
        if controller:
            controller.select_first_entry()
        else:
            TreeController.select_first_entry_in_tree(self.tree)
    
    def change_project(self, new_project):
        self.project_name = new_project
        self.setWindowTitle(_("Enhanced Compendium - {}").format(self.project_name))
        self.setup_compendium_file()
        self._reset_compendium_watchers()
        self.populate_compendium()

    def setup_compendium_file(self):
        """Set up the compendium file path for the selected project."""
        project_dir = os.path.join(os.getcwd(), "Projects", self.sanitize(self.project_name))
        self.compendium_file = os.path.join(project_dir, "compendium.json")
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)
        if DEBUG:
            logger.debug("Loading compendium from: %s", self.compendium_file)
        # Create a model to manage compendium data and I/O
        self.model = CompendiumModel(self.compendium_file)
        try:
            self.model.load()
        except Exception:
            # Ensure model has a sane default if load fails
            self.model = CompendiumModel(self.compendium_file)
            self.model.save()
        # expose compendium_data for backward compatibility
        self.compendium_data = self.model.as_data()
        # Create a TreeController to manage the tree view
        try:
            self.tree_controller = TreeController(self.tree, self.model)
        except Exception:
            # If tree controller cannot be created (during tests/headless), continue without it
            self.tree_controller = None
        self._reset_compendium_watchers()
    
    def create_tree_view(self):
        """Create the left panel: a tree view (with a search bar) for categories and entries."""
        self.tree_widget = QWidget()
        tree_layout = QVBoxLayout(self.tree_widget)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText(_("Search entries and tags..."))
        tree_layout.addWidget(self.search_bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel(_("Compendium"))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        enable_tree_hand_cursor(self.tree)
        tree_layout.addWidget(self.tree)
        self.main_splitter.addWidget(self.tree_widget)
    
    def create_center_panel(self):
        """Create the center panel with a header and a tabbed view for content, details, relationships, and images."""
        # Use EntryEditor to encapsulate the center panel
        from .entry_editor import EntryEditor

        self.center_widget = EntryEditor(self)
        # Maintain compatibility with attribute names used elsewhere
        self.entry_name_label = self.center_widget.entry_name_label
        self.save_button = self.center_widget.save_button
        self.alias_line_edit = self.center_widget.alias_line_edit
        self.track_checkbox = self.center_widget.track_checkbox
        self.editor = self.center_widget.editor
        self.details_editor = self.center_widget.details_editor
        self.relationships_list = self.center_widget.relationships_list
        # expose relationship controls for compatibility
        self.rel_entry_combo = self.center_widget.rel_entry_combo
        self.rel_type_combo = self.center_widget.rel_type_combo
        self.add_rel_button = self.center_widget.add_rel_button
        # expose image control buttons
        self.add_image_button = self.center_widget.add_image_button
        self.remove_image_button = self.center_widget.remove_image_button
        self.image_container = self.center_widget.image_container
        self.image_scroll = self.center_widget.image_scroll
        self.tabs = self.center_widget.tabs

    # image button attributes mapped

        self.main_splitter.addWidget(self.center_widget)
    
    def create_right_panel(self):
        """Create the right panel with tag management."""
        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)
        
        tags_group = QGroupBox(_("Tags"))
        tags_layout = QVBoxLayout(tags_group)
        tag_input_layout = QHBoxLayout()
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText(_("Add new tag..."))
        tag_input_layout.addWidget(self.tag_input)
        self.add_tag_button = QPushButton("+")
        self.add_tag_button.setFixedWidth(30)
        self.add_tag_button.setToolTip(_("add a tag to your entry"))
        tag_input_layout.addWidget(self.add_tag_button)
        tags_layout.addLayout(tag_input_layout)
        self.tags_list = QListWidget()
        self.tags_list.setContextMenuPolicy(Qt.CustomContextMenu)
        tags_layout.addWidget(self.tags_list)
        right_layout.addWidget(tags_group)
        self.main_splitter.addWidget(self.right_widget)
    
    def populate_compendium(self):
        """Load compendium data from the file and populate the UI."""
    # populate_compendium
        # Prefer using the TreeController to populate the tree if available
        try:
            self.compendium_data = self.model.as_data()
            if getattr(self, 'tree_controller', None):
                self.tree_controller.populate_tree()
            else:
                # Fallback to inline population for environments without TreeController
                self.tree.clear()
                bold_font = QFont()
                bold_font.setBold(True)
                for cat in self.compendium_data.get("categories", []):
                    cat_item = QTreeWidgetItem(self.tree, [cat.get("name", "Unnamed Category")])
                    cat_item.setData(0, Qt.UserRole, "category")
                    cat_item.setFont(0, bold_font)
                    cat_item.setBackground(0, QBrush(ThemeManager.get_category_background_color()))
                    for entry in cat.get("entries", []):
                        entry_name = entry.get("name", "Unnamed Entry")
                        entry_item = QTreeWidgetItem(cat_item, [entry_name])
                        entry_item.setData(0, Qt.UserRole, "entry")
                        normalized_content, changed_flag = self.model.normalize_entry_content(entry)
                        entry_item.setData(1, Qt.UserRole, normalized_content.get("description", ""))
                        entry_item.setData(2, Qt.UserRole, entry.get("uuid"))
                        if entry_name in self.compendium_data.get("extensions", {}).get("entries", {}):
                            extended_data = self.compendium_data["extensions"]["entries"][entry_name]
                            tags = extended_data.get("tags", [])
                            if tags:
                                first_tag = tags[0]
                                tag_color = first_tag["color"] if isinstance(first_tag, dict) else "#000000"
                                entry_item.setForeground(0, QBrush(QColor(tag_color)))
                    cat_item.setExpanded(True)
            # Update relations UI
            # update relation combo
            try:
                self._refresh_relation_combo()
            except Exception as ex:
                raise
            self._reset_compendium_watchers()
        except Exception as e:
            if DEBUG:
                logger.exception("Error populating compendium from model: %s", e)
            QMessageBox.warning(self, _("Error"), _("Failed to load compendium data: {}").format(str(e)))
            self._reset_compendium_watchers()

    def _reset_compendium_watchers(self):
        if not hasattr(self, "file_watcher") or self.file_watcher is None:
            return
        watcher = self.file_watcher
        try:
            watcher.clear()
            if getattr(self, "compendium_file", None):
                compendium_dir = os.path.dirname(self.compendium_file)
                if os.path.isdir(compendium_dir):
                    watcher.add_watch(compendium_dir)
                if os.path.exists(self.compendium_file):
                    watcher.add_watch(self.compendium_file)
        except Exception:
            # ignore watcher errors in constrained environments
            pass

    def _on_compendium_path_changed(self, _path):
        if DEBUG:
            logger.debug("Compendium file change detected; scheduling reload")
        self._reset_compendium_watchers()
        if self.dirty:
            self._pending_external_reload = True
            return
        self._reload_timer.start()

    def _perform_compendium_reload(self):
        if self.dirty:
            self._pending_external_reload = True
            return
        if self._reload_timer.isActive():
            self._reload_timer.stop()
        self._pending_external_reload = False
        current_entry = getattr(self, "current_entry", None)
        self.populate_compendium()
        if current_entry:
            self._select_entry_by_name(current_entry)
        else:
            controller = getattr(self, 'tree_controller', None)
            if controller:
                controller.select_first_entry()
            else:
                TreeController.select_first_entry_in_tree(self.tree)
        self.compendium_updated.emit(self.project_name)

    def _apply_pending_external_reload_if_needed(self):
        if getattr(self, "_pending_external_reload", False) and not self.dirty:
            if self._reload_timer.isActive():
                self._reload_timer.stop()
            self._perform_compendium_reload()
    
    def connect_signals(self):
        """Connect UI signals to their respective handlers."""
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree.currentItemChanged.connect(self.on_item_changed)
        self.search_bar.textChanged.connect(self.filter_tree)
        self.save_button.clicked.connect(self.on_save_button_clicked)
        self.add_tag_button.clicked.connect(self.add_tag)
        self.tag_input.returnPressed.connect(self.add_tag)
        self.editor.textChanged.connect(self.mark_dirty)
        self.details_editor.textChanged.connect(lambda: self.mark_dirty())
        self.alias_line_edit.textChanged.connect(self.mark_dirty)
        self.track_checkbox.toggled.connect(self.mark_dirty)
        self.tags_list.customContextMenuRequested.connect(self.show_tags_context_menu)
        self.add_rel_button.clicked.connect(self.add_relationship)
        self.relationships_list.customContextMenuRequested.connect(self.show_relationships_context_menu)
        self.relationships_list.itemDoubleClicked.connect(self.open_related_entry)
        self.add_image_button.clicked.connect(self.add_image)
        self.remove_image_button.clicked.connect(self.remove_selected_image)
        # Register editable widgets so we can detect global clicks outside them
        try:
            self._editable_widgets = [self.editor, self.details_editor, self.alias_line_edit]
        except Exception:
            self._editable_widgets = []
        # Install app-level event filter to intercept clicks outside editable widgets
        try:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
                self._app_filter_installed = True
            else:
                self._app_filter_installed = False
        except Exception:
            self._app_filter_installed = False
    
    def show_tree_context_menu(self, pos):
        """Display context menu for the tree view."""
        from .menu_helpers import build_tree_menu
        item = self.tree.itemAt(pos)
        original_item_name = item.text(0) if self._is_item_valid(item) else None
        original_item_type = item.data(0, Qt.UserRole) if self._is_item_valid(item) else None
        menu = build_tree_menu(self, item)
        action = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if action is None:
            return
        text = action.text()
        # Map selected text to handlers (keeps logic centralized and easy to change)
        if text == _("New Category"):
            self.new_category()
            return
        if text == _("Analyze Scene with AI"):
            self.analyze_scene_with_ai()
            return
        # For item-specific actions, handle via text mapping
        if not self._is_item_valid(item):
            item = None
        if item is None:
            if original_item_type == "entry" and original_item_name:
                item = self._select_entry_by_name(original_item_name)
            elif original_item_type == "category" and original_item_name:
                item = TreeController.find_category_item_in_tree(self.tree, original_item_name)
        if not self._is_item_valid(item):
            return
        item_type = original_item_type if original_item_type is not None else item.data(0, Qt.UserRole)
        if item_type == "category":
            if text == _("New Entry"):
                self.new_entry(item)
            elif text == _("Delete Category"):
                self.delete_category(item)
            elif text == _("Rename Category"):
                self.rename_item(item, "category")
            elif text == _("Move Up"):
                self.move_item(item, "up")
            elif text == _("Move Down"):
                self.move_item(item, "down")
        elif item_type == "entry":
            if text == _("Save Entry"):
                self.save_entry(item)
            elif text == _("Delete Entry"):
                self.delete_entry(item)
            elif text == _("Rename Entry"):
                self.rename_item(item, "entry")
            elif text == _("Move To..."):
                self.move_entry(item)
            elif text == _("Move Up"):
                self.move_item(item, "up")
            elif text == _("Move Down"):
                self.move_item(item, "down")
            elif text == _("Analyze Scene with AI"):
                self.analyze_scene_with_ai()
    
    def show_tags_context_menu(self, pos):
        """Show context menu for tag actions: remove, move up, move down."""
        from .menu_helpers import build_tags_menu
        item = self.tags_list.itemAt(pos)
        menu = build_tags_menu(self, item)
        action = menu.exec_(self.tags_list.viewport().mapToGlobal(pos))
        if not item or action is None:
            return
        text = action.text()
        if text == _("Remove Tag"):
            self.tags_list.takeItem(self.tags_list.row(item))
            self.mark_dirty()
            self.update_entry_indicator()
        elif text == _("Move Up"):
            row = self.tags_list.row(item)
            if row > 0:
                self.tags_list.takeItem(row)
                self.tags_list.insertItem(row - 1, item)
                self.mark_dirty()
                self.update_entry_indicator()
        elif text == _("Move Down"):
            row = self.tags_list.row(item)
            if row < self.tags_list.count() - 1:
                self.tags_list.takeItem(row)
                self.tags_list.insertItem(row + 1, item)
                self.mark_dirty()
                self.update_entry_indicator()
    
    def show_relationships_context_menu(self, pos):
        """Show context menu for relationship removal."""
        from .menu_helpers import build_relationships_menu
        item = self.relationships_list.itemAt(pos)
        menu = build_relationships_menu(self, item)
        action = menu.exec_(self.relationships_list.viewport().mapToGlobal(pos))
        if not item or action is None:
            return
        if action.text() == _("Remove Relationship"):
            self.relationships_list.takeTopLevelItem(self.relationships_list.indexOfTopLevelItem(item))
            self.mark_dirty()
    
    def add_tag(self):
        """Add a new tag to the current entry with a chosen color."""
        if not hasattr(self, 'current_entry'):
            return
        tag_text = self.tag_input.text().strip()
        if not tag_text:
            return
        for i in range(self.tags_list.count()):
            if self.tags_list.item(i).text().lower() == tag_text.lower():
                return
        color = QColorDialog.getColor(QColor("black"), self, _("Select Tag Color"))
        if not color.isValid():
            return
        item = QListWidgetItem(tag_text)
        item.setData(Qt.UserRole, color.name())
        item.setForeground(QBrush(color))
        item.setToolTip(_("right-click to move the tag within this list - this impacts the colour of your entry"))
        self.tags_list.addItem(item)
        self.tag_input.clear()
        self.mark_dirty()
        self.update_entry_indicator()
    
    def add_relationship(self):
        """Add a new relationship to the current entry."""
        if not hasattr(self, 'current_entry'):
            return
        related_entry = self.rel_entry_combo.currentText()
        rel_type = self.rel_type_combo.currentText()
        if not related_entry or not rel_type:
            return
        rel_item = QTreeWidgetItem([related_entry, rel_type])
        self.relationships_list.addTopLevelItem(rel_item)
        self.mark_dirty()
        self.update_entry_indicator()
    
    def open_related_entry(self, item, column):
        """Double-click a relationship to open the corresponding entry."""
        entry_name = item.text(0)
        self._select_entry_by_name(entry_name)

    def sanitize(self, text):
        return re.sub(r'\W+', '', text)
    
    def analyze_scene_with_ai(self):
        """Analyze the current scene with AI and update compendium entries.

        Delegates the LLM prompt/parse work to `ai_integration.analyze_scene` and
        keeps UI responsibilities (dialogs, warnings, saving) here.
        """
        from .ai_integration import analyze_scene

        # Check if project_window is available and has scene content
        if not hasattr(self, 'project_window') or not self.project_window:
            QMessageBox.warning(self, _("Warning"), _("No project window available for scene analysis."))
            return

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
                logger.exception("Error loading compendium: %s", e)

        overrides = LLMSettingsDialog.show_dialog(
            self,
            default_provider=WWSettingsManager.get_active_llm_name(),
            default_model=WWSettingsManager.get_active_llm_config().get("model", None),
            default_timeout=60,
        )
        if not overrides:
            return

        success, ai_compendium, err = analyze_scene(scene_content, current_compendium, overrides, context={})
        if not success:
            QMessageBox.warning(self, _("Error"), _("Failed to analyze scene: {}").format(err))
            return

        try:
            dialog = AICompendiumDialog(ai_compendium, self.compendium_file, self)
            if dialog.exec_() == QDialog.Accepted:
                self.save_ai_analysis(dialog.get_compendium_data())
        except Exception as e:
            QMessageBox.warning(self, _("Error"), _("Failed to analyze scene: {}").format(str(e)))
    
    def save_ai_analysis(self, ai_compendium):
        """Save AI-generated compendium entries, merging with existing data."""
        try:
            # Delegate merging of AI compendium to the model
            self.model.apply_ai_compendium(ai_compendium)
            self.compendium_data = self.model.as_data()
            self.populate_compendium()
            self.compendium_updated.emit(self.project_name)
            QMessageBox.information(self, _("Success"), _("Compendium updated successfully."))
        except Exception as e:
            QMessageBox.warning(self, _("Error"), _("Failed to save compendium: {}").format(str(e)))

    def add_image(self):
        """Add an image to the current entry."""
        if not hasattr(self, 'current_entry'):
            return
        file_path, unused = QFileDialog.getOpenFileName(self, _("Select Image"), "", "Image Files (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not file_path:
            return
        project_dir = os.path.dirname(self.compendium_file)
        images_dir = os.path.join(project_dir, "images")
        if not os.path.exists(images_dir):
            os.makedirs(images_dir)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unused, ext = os.path.splitext(file_path)
        sanitized_entry_name = self.sanitize(self.current_entry)
        new_filename = f"{sanitized_entry_name}_{timestamp}{ext}"
        new_path = os.path.join(images_dir, new_filename)
        try:
            shutil.copy2(file_path, new_path)
            # update model
            ext = self.model.compendium_data.setdefault("extensions", {}).setdefault("entries", {})
            if self.current_entry not in ext:
                ext[self.current_entry] = {}
            if "images" not in ext[self.current_entry]:
                ext[self.current_entry]["images"] = []
            ext[self.current_entry]["images"].append(new_filename)
            self.model.save()
            self.compendium_data = self.model.as_data()
            self.center_widget.add_image_from_path(new_path, new_filename)
            self.mark_dirty()
            self.update_entry_indicator()
        except Exception as e:
            if DEBUG:
                logger.exception("Error copying image: %s", e)
            QMessageBox.warning(self, _("Error"), _("Failed to copy image: {}").format(str(e)))
    
    def remove_selected_image(self):
        """Remove the selected image."""
        filename = self.center_widget.get_selected_image_filename()
        if not filename:
            return
        if (hasattr(self, 'current_entry') and 
            self.current_entry in self.model.compendium_data.get("extensions", {}).get("entries", {}) and
            "images" in self.model.compendium_data["extensions"]["entries"][self.current_entry]):
            if filename in self.model.compendium_data["extensions"]["entries"][self.current_entry]["images"]:
                self.model.compendium_data["extensions"]["entries"][self.current_entry]["images"].remove(filename)
            self.model.save()
            self.compendium_data = self.model.as_data()
            self.center_widget.remove_selected_image_widget()
            self.mark_dirty()
            self.update_entry_indicator()
    
    def filter_tree(self, text):
        """Filter the tree view based on the search text (searches entry names and tags)."""
        data = getattr(self, "compendium_data", {})
        if getattr(self, 'tree_controller', None):
            self.tree_controller.filter_tree(text, data)
        else:
            TreeController.filter_tree_items(self.tree, text, data)
    
    def update_entry_indicator(self):
        """Update the entry indicator (coloring the entry name based on the first tag's color)."""
        if not hasattr(self, 'current_entry') or not hasattr(self, 'current_entry_item'):
            return
        entry_name = self.current_entry
        entry_item = self.current_entry_item
        data = getattr(self, "compendium_data", {})
        if getattr(self, 'tree_controller', None):
            self.tree_controller.update_entry_indicator(entry_item, entry_name, data)
        else:
            TreeController.apply_entry_indicator(entry_item, entry_name, data)

    def eventFilter(self, obj, event):
        """Intercept global mouse presses and save the current entry if the
        user clicked outside any registered editable widgets while the
        editor is dirty.
        """
        try:
            etype = event.type()
        except Exception:
            etype = None

        if etype == QEvent.MouseButtonPress and getattr(self, '_editable_widgets', None):
            # Determine global click position
            gp = None
            gp_getter = getattr(event, 'globalPos', None)
            if callable(gp_getter):
                try:
                    gp = gp_getter()
                except Exception:
                    gp = None
            if gp is None:
                # fallback: try mapping local pos to global using obj
                pos_getter = getattr(event, 'pos', None)
                if callable(pos_getter) and hasattr(obj, 'mapToGlobal'):
                    try:
                        local = pos_getter()
                        gp = obj.mapToGlobal(local)
                    except Exception:
                        gp = None
            if gp is None:
                try:
                    gp = QCursor.pos()
                except Exception:
                    gp = None

            if gp is not None:
                # If the click is outside all editable widget geometries, attempt save
                clicked_outside_all = True
                for w in self._editable_widgets:
                    try:
                        if not w:
                            continue
                        # map widget rect to global coordinates
                        rect = QRect(w.mapToGlobal(w.rect().topLeft()), w.mapToGlobal(w.rect().bottomRight()))
                        if rect.contains(gp):
                            clicked_outside_all = False
                            break
                    except Exception:
                        # ignore problematic widgets
                        continue

                if clicked_outside_all and self.dirty:
                    # Attempt to save; if save fails, return False to allow widgets to handle focus events
                    try:
                        self._save_dirty_entry_if_needed()
                    except Exception:
                        pass

        return super().eventFilter(obj, event)
    
    def save_entry(self, entry_item):
        """Save changes to a specific entry."""
        entry_name = entry_item.text(0)
        entry_item.setData(1, Qt.UserRole, self.editor.toPlainText())
        if entry_item.data(2, Qt.UserRole) is None:
            entry_item.setData(2, Qt.UserRole, str(uuid.uuid4()))
        self.save_extended_data()
        self.save_compendium_to_file()
        self.dirty = False
        self._apply_pending_external_reload_if_needed()
    
    def on_save_button_clicked(self):
        """Handle the Save button by delegating to save_entry for the current item.

        This ensures the editor content is copied into the tree item before
        persistence, consolidating the save logic to a single path.
        """
        if not hasattr(self, 'current_entry') or not hasattr(self, 'current_entry_item'):
            return
        try:
            self.save_entry(self.current_entry_item)
        except Exception as e:
            if DEBUG:
                logger.exception("Error saving current entry via button: %s", e)

    def save_extended_data(self):
        """Extract and save extended data for the current entry (details, tags, relationships, images)."""
        if not hasattr(self, 'current_entry'):
            return
        ext = self.model.compendium_data.setdefault("extensions", {}).setdefault("entries", {})
        if self.current_entry not in ext:
            ext[self.current_entry] = {}

        # Details
        ext[self.current_entry]["details"] = self.details_editor.toPlainText()

        # Aliases
        aliases = [alias.strip() for alias in self.alias_line_edit.text().split(',') if alias.strip()]
        if aliases:
            ext[self.current_entry]["aliases"] = aliases
        else:
            ext[self.current_entry].pop("aliases", None)

        # Track by name
        track_by_name = self.track_checkbox.isChecked()
        ext[self.current_entry]["track_by_name"] = track_by_name

        # Tags
        tags = []
        for i in range(self.tags_list.count()):
            item = self.tags_list.item(i)
            tags.append({"name": item.text(), "color": item.data(Qt.UserRole)})
        if tags:
            ext[self.current_entry]["tags"] = tags
        else:
            ext[self.current_entry].pop("tags", None)

        # Relationships
        relationships = []
        for i in range(self.relationships_list.topLevelItemCount()):
            item = self.relationships_list.topLevelItem(i)
            relationships.append({"name": item.text(0), "type": item.text(1)})
        if relationships:
            ext[self.current_entry]["relationships"] = relationships
        else:
            ext[self.current_entry].pop("relationships", None)

        # If no extended data remains for this entry, remove the key
        if not ext[self.current_entry]:
            ext.pop(self.current_entry, None)

        # Persist changes
        self.model.save()
        self.compendium_data = self.model.as_data()
        self.update_entry_indicator()
    
    def get_compendium_data(self):
        """Reconstruct the full compendium data."""
        data = {"categories": []}
        existing_categories = {cat.get("name"): cat for cat in self.compendium_data.get("categories", [])}
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_item = root.child(i)
            cat_name = cat_item.text(0)
            cat_data = {"name": cat_name, "entries": []}
            existing_entries = {}
            if cat_name in existing_categories:
                existing_entries = {entry.get("name"): entry for entry in existing_categories[cat_name].get("entries", [])}
            for j in range(cat_item.childCount()):
                entry_item = cat_item.child(j)
                entry_name = entry_item.text(0)
                existing_entry = existing_entries.get(entry_name, {})
                entry_data = dict(existing_entry) if existing_entry else {}
                entry_data["name"] = entry_name
                entry_uuid = entry_item.data(2, Qt.UserRole)
                if entry_uuid:
                    entry_data["uuid"] = entry_uuid
                description = entry_item.data(1, Qt.UserRole) or ""
                existing_content = entry_data.get("content", {})
                if isinstance(existing_content, dict):
                    content_dict = dict(existing_content)
                    content_dict["description"] = description
                else:
                    content_dict = {"description": description}
                entry_data["content"] = content_dict
                cat_data["entries"].append(entry_data)
            data["categories"].append(cat_data)
        data["extensions"] = self.compendium_data.get("extensions", {"entries": {}})
        return data
    
    def save_compendium_to_file(self):
        """Save the compendium data back to the file."""
        try:
            data = self.get_compendium_data()
            # update model and save
            self.model.compendium_data = data
            self.model.save()
            self.compendium_data = self.model.as_data()
            if DEBUG:
                logger.debug("Saved compendium data to %s", self.compendium_file)
            
            # Emit signal with project name
            self.compendium_updated.emit(self.project_name)
            self._reset_compendium_watchers()
        except Exception as e:
            if DEBUG:
                logger.exception("Error saving compendium data: %s", e)
            QMessageBox.warning(self, _("Error"), _("Failed to save compendium data: {}").format(str(e)))
    
    def new_category(self):
        if not self._save_dirty_entry_if_needed():
            return
        name, ok = QInputDialog.getText(self, _("New Category"), _("Category name:"))
        if ok and name:
            # update model and refresh tree
            self.model.add_category(name)
            self.compendium_data = self.model.as_data()
            self.populate_compendium()
            self._rebind_current_entry_item()
    
    def new_entry(self, category_item):
        category_name = category_item.text(0) if self._is_item_valid(category_item) else None
        if not self._save_dirty_entry_if_needed():
            return
        if category_name is None:
            return
        name, ok = QInputDialog.getText(self, _("New Entry"), _("Entry name:"))
        if ok and name:
            # add to model then refresh
            payload = {"name": name, "content": {"description": ""}, "uuid": str(uuid.uuid4())}
            self.model.add_entry(category_name, payload)
            self.compendium_data = self.model.as_data()
            self.populate_compendium()
            # find and select the new entry
            self._select_entry_by_name(name)
            self._refresh_relation_combo()
    
    def delete_category(self, category_item):
        category_name = category_item.text(0) if self._is_item_valid(category_item) else None
        if category_name is None:
            return
        if not self._save_dirty_entry_if_needed():
            return
        confirm = QMessageBox.question(self, _("Confirm Deletion"),
            _("Are you sure you want to delete the category '{}' and all its entries?").format(category_name),
            QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            # remove entries from model
            # remove category by rebuilding categories without it
            cats = [c for c in self.model.get_categories() if c.get("name") != category_name]
            self.model.compendium_data["categories"] = cats
            # remove extensions for entries in that category
            # (extensions keyed by name - remove any matching names)
            for c in cats:
                pass
            self.model.save()
            self.compendium_data = self.model.as_data()
            self.populate_compendium()
            self._refresh_relation_combo()
            self._rebind_current_entry_item()
    
    def delete_entry(self, entry_item):
        entry_name = entry_item.text(0) if self._is_item_valid(entry_item) else None
        if entry_name is None:
            return
        if not self._save_dirty_entry_if_needed():
            return
        confirm = QMessageBox.question(self, _("Confirm Deletion"),
            _("Are you sure you want to delete the entry '{}'?\n").format(entry_name),
            QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            # let the model remove the entry and save
            self.model.delete_entry(entry_name)
            self.compendium_data = self.model.as_data()
            # refresh tree
            self.populate_compendium()
            if hasattr(self, 'current_entry') and self.current_entry == entry_name:
                self.clear_entry_ui()
            else:
                self._rebind_current_entry_item()
            self._refresh_relation_combo()
    
    def rename_item(self, item, item_type):
        current_text = item.text(0)
        new_text, ok = QInputDialog.getText(self, _("Rename {}").format(item_type.capitalize()), _("New name:"), text=current_text)
        if ok and new_text:
            if item_type == "entry":
                old_name = current_text
                # update model entries names
                # find entry and rename in model
                found = self.model.find_entry(old_name)
                if found:
                    cat_name, entry = found
                    entry["name"] = new_text
                    # move extension data key if present
                    ext = self.model.compendium_data.get("extensions", {}).get("entries", {})
                    if old_name in ext:
                        ext[new_text] = ext.pop(old_name)
                    self.model.save()
                    self.compendium_data = self.model.as_data()
                item.setText(0, new_text)
                if hasattr(self, 'current_entry') and self.current_entry == old_name:
                    self.current_entry = new_text
                    self.entry_name_label.setText(new_text)
            else:
                item.setText(0, new_text)
            self.save_compendium_to_file()
            if item_type == "entry":
                self._refresh_relation_combo()
    
    def move_item(self, item, direction):
        moved = False
        if getattr(self, 'tree_controller', None):
            moved = self.tree_controller.move_item(item, direction)
        else:
            moved = TreeController.move_item_in_tree(self.tree, item, direction)
        if moved:
            self.save_compendium_to_file()
    
    def move_entry(self, entry_item):
        from PyQt5.QtGui import QCursor
        menu = QMenu(self)
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_item = root.child(i)
            if cat_item.data(0, Qt.UserRole) == "category":
                action = menu.addAction(cat_item.text(0))
                action.setData(cat_item)
        selected_action = menu.exec_(QCursor.pos())
        if selected_action is not None:
            target_category = selected_action.data()
            if target_category is not None:
                current_parent = entry_item.parent()
                if current_parent is not None:
                    current_parent.removeChild(entry_item)
                target_category.addChild(entry_item)
                target_category.setExpanded(True)
                self.tree.setCurrentItem(entry_item)
                self.save_compendium_to_file()
    
    def _is_item_valid(self, item: QTreeWidgetItem | None) -> bool:
        # Use shared helper which is SIP-aware and easier to test
        return is_item_valid(item)

    def on_item_changed(self, current, previous):
        if not self._is_item_valid(previous):
            previous = None
        if not self._is_item_valid(current):
            current = None
        # Save changes to the previous entry if it exists and is dirty
        if previous is not None and previous.data(0, Qt.UserRole) == "entry" and self.dirty:
            self.save_entry(previous)

        if current is None:
            self.clear_entry_ui()
            return

        item_type = current.data(0, Qt.UserRole)
        if item_type == "entry":
            entry_name = current.text(0)
            self.load_entry(entry_name, current)
        else:
            self.clear_entry_ui()
    
    def load_entry(self, entry_name, entry_item):
        # Save changes to the current entry if it exists and is dirty
        if hasattr(self, 'current_entry') and hasattr(self, 'current_entry_item') and self.dirty:
            # Persist the currently edited entry using the consolidated save path
            try:
                self.save_entry(self.current_entry_item)
            except Exception:
                # If save_entry fails for some reason, swallow to avoid blocking load
                pass

        self.current_entry = entry_name
        self.current_entry_item = entry_item
        self.entry_name_label.setText(entry_name)
        self.editor.blockSignals(True)
        content = entry_item.data(1, Qt.UserRole)
        self.editor.setPlainText(content)
        self.editor.blockSignals(False)
        has_extended = entry_name in self.compendium_data["extensions"]["entries"]
        if has_extended:
            extended_data = self.compendium_data["extensions"]["entries"][entry_name]
            self.details_editor.blockSignals(True)
            self.details_editor.setPlainText(extended_data.get("details", ""))
            self.details_editor.blockSignals(False)
            self.alias_line_edit.blockSignals(True)
            aliases_data = extended_data.get("aliases", [])
            if isinstance(aliases_data, str):
                alias_text = aliases_data
            else:
                alias_text = ', '.join(aliases_data)
            self.alias_line_edit.setText(alias_text)
            self.alias_line_edit.blockSignals(False)
            self.track_checkbox.blockSignals(True)
            self.track_checkbox.setChecked(extended_data.get("track_by_name", True))
            self.track_checkbox.blockSignals(False)
            self.tags_list.clear()
            for tag in extended_data.get("tags", []):
                if isinstance(tag, dict):
                    tag_name = tag.get("name", "")
                    tag_color = tag.get("color", "#000000")
                else:
                    tag_name = tag
                    tag_color = "#000000"
                item = QListWidgetItem(tag_name)
                item.setData(Qt.UserRole, tag_color)
                item.setForeground(QBrush(QColor(tag_color)))
                item.setToolTip(_("right-click to move the tag within this list - this impacts the colour of your entry"))
                self.tags_list.addItem(item)
            self.relationships_list.clear()
            for rel in extended_data.get("relationships", []):
                rel_item = QTreeWidgetItem([rel.get("name", ""), rel.get("type", "")])
                self.relationships_list.addTopLevelItem(rel_item)
            images = extended_data.get("images", [])
            project_dir = os.path.dirname(self.compendium_file)
            images_dir = os.path.join(project_dir, "images")
            self.center_widget.load_images(images, images_dir)
        else:
            self.details_editor.blockSignals(True)
            self.details_editor.clear()
            self.details_editor.blockSignals(False)
            self.alias_line_edit.blockSignals(True)
            self.alias_line_edit.clear()
            self.alias_line_edit.blockSignals(False)
            self.track_checkbox.blockSignals(True)
            self.track_checkbox.setChecked(True)
            self.track_checkbox.blockSignals(False)
            self.tags_list.clear()
            self.relationships_list.clear()
            self.center_widget.clear_images()
        self.update_entry_indicator()
        self.dirty = False
        self.tabs.show()
    
    def clear_entry_ui(self):
        self.entry_name_label.setText(_("No entry selected"))
        self.editor.clear()
        self.details_editor.blockSignals(True)
        self.details_editor.clear()
        self.details_editor.blockSignals(False)
        self.alias_line_edit.blockSignals(True)
        self.alias_line_edit.clear()
        self.alias_line_edit.blockSignals(False)
        self.track_checkbox.blockSignals(True)
        self.track_checkbox.setChecked(True)
        self.track_checkbox.blockSignals(False)
        self.tags_list.clear()
        self.relationships_list.clear()
        self.center_widget.clear_images()
        self.dirty = False
        self.tabs.hide()
        if hasattr(self, 'current_entry'):
            del self.current_entry
        if hasattr(self, 'current_entry_item'):
            del self.current_entry_item
    
    def open_with_entry(self, project_name, entry_name):
        """ make visible and raise window, then show the entry."""
        self.populate_project_combo(project_name)
        self.change_project(project_name)
        self.show()
        self.raise_()
        if entry_name:
            self._select_entry_by_name(entry_name)