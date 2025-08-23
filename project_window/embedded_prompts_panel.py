import os
import uuid
from typing import Dict, Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QPushButton, QMenu, QInputDialog, QMessageBox, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QApplication, QHeaderView
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QBrush
from muse.prompt_utils import get_prompt_categories, load_prompts, get_default_prompt, save_prompts
from settings.llm_api_aggregator import WWApiAggregator
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager
from settings.provider_info_dialog import ProviderInfoDialog

class CustomTextEdit(QTextEdit):
    """Custom QTextEdit to handle focus-out and hide events."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.panel = parent  # Reference to EmbeddedPromptsPanel

    def focusOutEvent(self, event):
        """Handle focus-out event and notify the parent panel."""
        if hasattr(self.panel, '_on_editor_focus_out'):
            self.panel._on_editor_focus_out()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        """Handle hide event and immediately apply pending changes."""
        if hasattr(self.panel, '_apply_pending_changes'):
            # Update pending changes before applying to ensure latest text is captured
            if hasattr(self.panel, '_update_pending_changes'):
                self.panel._update_pending_changes()
            self.panel._apply_pending_changes()
        super().hideEvent(event)

class EmbeddedPromptsPanel(QWidget):
    """Panel for managing prompts in the main window's sidebar and editor."""
    
    SAVE_DELAY = 7000  # wait time (microseconds) before saving a user edit
    
    def __init__(self, project_name: str, controller, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project_name = project_name
        self.controller = controller
        self.prompts_file = WWSettingsManager.get_project_path(file="prompts.json")
        self.backup_file = WWSettingsManager.get_project_path(file="prompts.bak.json")
        self.prompts_data: Dict[str, List[Dict]] = {}
        self.current_prompt_item: Optional[QTreeWidgetItem] = None
        self.pending_changes: Dict[str, Dict] = {}  # Store pending changes by prompt ID
        self.selected_model: Optional[str] = None
        self.pending_model: Optional[str] = None
        
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(self.SAVE_DELAY)
        self.save_timer.timeout.connect(self._apply_pending_changes)
        
        self.init_ui()
        self.load_prompts()
        self.tree.expandAll()

    def init_ui(self) -> None:
        """Initialize the user interface components."""
        self.setLayout(self._create_main_layout())
        self._setup_splitter()
        self._setup_tree_widget()
        self._setup_editor_widget()
        self._setup_parameters_panel()
        self.update_provider_list()

    def _create_main_layout(self) -> QVBoxLayout:
        """Create the main layout for the panel."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        return layout

    def _setup_splitter(self) -> None:
        """Set up the splitter for tree and editor widgets."""
        self.splitter = QSplitter(Qt.Horizontal)
        self.layout().addWidget(self.splitter)

    def _setup_tree_widget(self) -> None:
        """Set up the tree widget for displaying prompts."""
        self.tree_widget = QWidget()
        tree_layout = QVBoxLayout(self.tree_widget)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([_("Prompts"), ""])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.setColumnWidth(1, 40)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree.setIndentation(5)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        
        tree_layout.addWidget(self.tree)
        self.splitter.addWidget(self.tree_widget)
        self.splitter.setStretchFactor(0, 1)

    def _setup_editor_widget(self) -> None:
        """Set up the editor widget for prompt text."""
        self.editor_widget = QWidget()
        right_layout = QVBoxLayout(self.editor_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self.editor = CustomTextEdit(self)  # Use custom QTextEdit subclass
        self.replicate_button = QPushButton(_("Replicate"))
        self.replicate_button.setToolTip(_("This is a read-only default prompt. Create a copy to edit it."))
        self.replicate_button.clicked.connect(self._replicate_prompt)
        self.replicate_button.hide()
        
        right_layout.addWidget(self.editor)
        right_layout.addWidget(self.replicate_button)
        self.splitter.addWidget(self.editor_widget)
        self.splitter.setStretchFactor(1, 2)

    def _setup_parameters_panel(self) -> None:
        """Set up the parameters panel for provider and model settings."""
        self.parameters_panel = QWidget()
        params_layout = QVBoxLayout(self.parameters_panel)
        
        model_group = self._create_model_group()
        settings_group = self._create_settings_group()
        
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: red;")
        self.status_label.hide()
        
        params_layout.addLayout(model_group)
        params_layout.addLayout(settings_group)
        params_layout.addWidget(self.status_label)
        self.parameters_panel.hide()
        
        self.editor_widget.layout().addWidget(self.parameters_panel)

    def _create_model_group(self) -> QHBoxLayout:
        """Create the model group layout for provider and model selection."""
        model_group = QHBoxLayout()
        
        provider_layout = QVBoxLayout()
        provider_header = QHBoxLayout()
        self.provider_label = QLabel(_("Provider:"))
        provider_info_button = QPushButton()
        provider_info_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/info.svg"))
        provider_info_button.setToolTip(_("Show Model Details"))
        provider_info_button.clicked.connect(self._show_provider_info)
        
        provider_header.addWidget(self.provider_label)
        provider_header.addWidget(provider_info_button)
        provider_header.addStretch()
        
        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(200)
        self.provider_combo.currentTextChanged.connect(self._on_parameter_changed)
        provider_layout.addLayout(provider_header)
        provider_layout.addWidget(self.provider_combo)
        
        model_layout = QVBoxLayout()
        model_header = QHBoxLayout()
        self.model_label = QLabel(_("Model:"))
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setToolTip(_("Refresh model list"))
        self.refresh_button.setMaximumWidth(30)
        self.refresh_button.clicked.connect(self._refresh_models)
        
        model_header.addWidget(self.model_label)
        model_header.addWidget(self.refresh_button)
        model_header.addStretch()
        
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(300)
        self.model_combo.currentTextChanged.connect(self._on_parameter_changed)
        
        model_layout.addLayout(model_header)
        model_layout.addWidget(self.model_combo)
        
        model_group.addLayout(provider_layout)
        model_group.addLayout(model_layout)
        return model_group

    def _create_settings_group(self) -> QHBoxLayout:
        """Create the settings group for max tokens and temperature."""
        settings_group = QHBoxLayout()
        
        tokens_layout = QVBoxLayout()
        self.max_tokens_label = QLabel(_("Max Tokens:"))
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1, 2147483647)
        self.max_tokens_spin.setValue(2000)
        self.max_tokens_spin.valueChanged.connect(self._on_parameter_changed)
        tokens_layout.addWidget(self.max_tokens_label)
        tokens_layout.addWidget(self.max_tokens_spin)
        
        temp_layout = QVBoxLayout()
        self.temp_label = QLabel(_("Temperature:"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(0.7)
        self.temp_spin.valueChanged.connect(self._on_parameter_changed)
        temp_layout.addWidget(self.temp_label)
        temp_layout.addWidget(self.temp_spin)
        
        settings_group.addLayout(tokens_layout)
        settings_group.addLayout(temp_layout)
        settings_group.addStretch()
        return settings_group

    def update_provider_list(self) -> None:
        """Update the provider combo box with available LLM providers."""
        self.provider_combo.clear()
        self.llm_configs = WWSettingsManager.get_llm_configs()
        self.active_config = WWSettingsManager.get_active_llm_name()
        
        for provider, config in self.llm_configs.items():
            display_name = f"{provider} ({config['provider']})"
            self.provider_combo.addItem(display_name, userData=provider)
            if provider == self.active_config:
                self.provider_combo.setCurrentText(display_name)
        
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)

    def _get_provider_display_name(self, provider: str) -> str:
        """Get the display name for a provider as stored in provider_combo."""
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == provider:
                return self.provider_combo.itemText(i)
        return provider  # Fallback to provider name if not found

    def _on_provider_changed(self, provider_text: str) -> None:
        """Handle provider combo box changes."""
        self._refresh_models(use_cache=True)
        self._update_pending_changes()
        self.save_timer.start()

    def _refresh_models(self, use_cache: bool = False) -> None:
        """Refresh the model list for the selected provider."""
        current_index = self.provider_combo.currentIndex()
        if current_index < 0:
            return
        
        provider_name = self.provider_combo.itemData(current_index)
        if not use_cache:
            self.model_combo.clear()
            self.model_combo.addItem(_("Loading models..."))
            self.model_combo.setEnabled(False)
            self.refresh_button.setEnabled(False)
            QApplication.processEvents()
        
        try:
            provider = WWApiAggregator.aggregator.get_provider(provider_name)
            models = provider.get_available_models(not use_cache)
            self._on_models_updated(models, None)
        except Exception as e:
            self._on_models_updated([], _("Error fetching models: {}").format(str(e)))

    def _on_models_updated(self, models: List[str], error_msg: Optional[str]) -> None:
        """Update the model combo box with available models."""
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.addItem(_("Custom..."))
        self.model_combo.setEnabled(True)
        self.refresh_button.setEnabled(True)
        
        if error_msg:
            self.status_label.setText(error_msg)
            self.status_label.show()
        else:
            self.status_label.hide()
        
        if self.pending_model:
            idx = self.model_combo.findText(self.pending_model)
            if idx != -1:
                self.model_combo.setCurrentIndex(idx)
            self.pending_model = None

    def load_prompts(self) -> None:
        """Load and validate prompts, ensuring IDs are present."""
        default_categories = get_prompt_categories()
        self.prompts_data = load_prompts(None) or {}
        
        id_added = False
        for cat in default_categories:
            if cat not in self.prompts_data or not self.prompts_data[cat]:
                default_prompt = get_default_prompt(cat)
                self.prompts_data[cat] = [default_prompt] if isinstance(default_prompt, dict) else default_prompt
                id_added = True
        
        for cat in self.prompts_data:
            if isinstance(self.prompts_data[cat], list):
                for item in self.prompts_data[cat]:
                    if isinstance(item, dict) and "id" not in item:
                        item["id"] = str(uuid.uuid4())
                        id_added = True
        
        if id_added:
            self._save_to_file()
        
        self.tree.clear()
        bold_font = QFont()
        bold_font.setBold(True)
        
        for cat in sorted(self.prompts_data.keys()):
            parent = QTreeWidgetItem(self.tree, [cat])
            parent.setData(0, Qt.UserRole, {"type": "category", "name": cat})
            parent.setFont(0, bold_font)
            parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
            plus_button = QPushButton(self.tree)
            plus_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/plus.svg"))
            plus_button.setFlat(True)
            plus_button.setMaximumSize(24, 24)
            plus_button.clicked.connect(lambda _, it=parent: self._add_new_prompt(it))
            self.tree.setItemWidget(parent, 1, plus_button)
            
            for prompt in self.prompts_data[cat]:
                child = QTreeWidgetItem(parent, [prompt["name"]])
                child.setData(0, Qt.UserRole, prompt)
                child.setToolTip(0, self._create_prompt_tooltip(prompt))

    def _on_current_item_changed(self, current: QTreeWidgetItem, previous: QTreeWidgetItem) -> None:
        """Handle tree item selection changes."""
        def _setCurrentItem(tree: QTreeWidget, item: QTreeWidgetItem):
            """You can't change the current item while handling item change"""
            timer = QTimer(tree)
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(lambda: tree.setCurrentItem(item))
            timer.start()

        # Capture current editor text before switching prompts
        if self.current_prompt_item:
            self._update_pending_changes()
        self._apply_pending_changes()  # Save any pending changes before switching
        self.current_prompt_item = current
        self.replicate_button.hide()
        self.parameters_panel.hide()
        
        if not current:
            return
        
        data = current.data(0, Qt.UserRole)
        if not data or data.get("type") == "category":
            if previous:
                _setCurrentItem(self.tree, previous)
            elif current.childCount() > 0:
                _setCurrentItem(self.tree, current.child(0))
            return
        
        is_default = data.get("default", False)
        self.editor.blockSignals(True)  # We are loading saved data, so this is not an edit
        self.editor.setPlainText(data.get("text", ""))
        self.editor.setReadOnly(is_default)
        self.editor.blockSignals(False)
        if is_default:
            self.replicate_button.show()
        
        # Use SettingsManager for default prompts, otherwise use prompt data
        active_provider = WWSettingsManager.get_active_llm_name()
        active_config = WWSettingsManager.get_active_llm_config() or {}
        active_model = active_config.get("model", "")
        
        provider = active_provider if is_default else data.get("provider", active_provider)
        model = active_model if is_default else data.get("model", active_model)
        
        provider_display = self._get_provider_display_name(provider)
        self.pending_model = model
        self.provider_combo.setCurrentText(provider_display)
        current_model = self.model_combo.currentText()
        if current_model != model:
            self._refresh_models(True)
            self.model_combo.setCurrentText(model)
        
        self.max_tokens_spin.setValue(data.get("max_tokens", 2000))
        self.temp_spin.setValue(data.get("temperature", 0.7))
        
        self.parameters_panel.setVisible(True)
        self.provider_combo.setEnabled(not is_default)
        self.model_combo.setEnabled(not is_default)
        self.temp_spin.setEnabled(not is_default)
        self.refresh_button.setEnabled(not is_default)

    def _on_parameter_changed(self) -> None:
        """Handle changes to provider, model, max tokens, or temperature."""
        if not self.current_prompt_item:
            return
        
        data = self.current_prompt_item.data(0, Qt.UserRole)
        if not data or data.get("type") != "prompt" or data.get("default", False):
            return
        
        self._update_pending_changes()
        self.save_timer.start()

    def _on_editor_focus_out(self) -> None:
        """Handle focus loss on the editor to update pending changes."""
        if not self.current_prompt_item:
            return
        
        data = self.current_prompt_item.data(0, Qt.UserRole)
        if not data or data.get("type") == "category" or data.get("default", False):
            return
        
        self._update_pending_changes()
        self.save_timer.start()

    def _update_pending_changes(self) -> None:
        """Update pending changes with current UI values."""
        if not self.current_prompt_item:
            return
        
        data = self.current_prompt_item.data(0, Qt.UserRole)
        prompt_id = data.get("id")
        
        # Create or update pending changes
        pending_data = self.pending_changes.get(prompt_id, data.copy())
        
        updated = False
        new_text = self.editor.toPlainText()
        if new_text != pending_data.get("text"):
            pending_data["text"] = new_text
            updated = True
        
        new_provider = self._get_provider_config()
        if new_provider != pending_data.get("provider"):
            pending_data["provider"] = new_provider
            updated = True
        
        new_model = self.model_combo.currentText()
        if new_model != pending_data.get("model"):
            pending_data["model"] = new_model
            updated = True
        
        new_max_tokens = self.max_tokens_spin.value()
        if new_max_tokens != pending_data.get("max_tokens"):
            pending_data["max_tokens"] = new_max_tokens
            updated = True
        
        new_temperature = self.temp_spin.value()
        if new_temperature != pending_data.get("temperature"):
            pending_data["temperature"] = new_temperature
            updated = True
        
        if updated:
            self.pending_changes[prompt_id] = pending_data
            self.current_prompt_item.setToolTip(0, self._create_prompt_tooltip(pending_data))

    def _apply_pending_changes(self) -> None:
        """Apply pending changes to prompts_data and save to file."""
        if not self.current_prompt_item or not self.pending_changes:
            return
        
        updated = False
        for prompt_id, pending_data in list(self.pending_changes.items()):  # Copy to avoid mod-during-iter
            # Find the category and prompt index by ID
            category = None
            prompt_index = None
            for cat, prompts in self.prompts_data.items():
                for idx, prompt in enumerate(prompts):
                    if prompt.get("id") == prompt_id:
                        category = cat
                        prompt_index = idx
                        break
                if category:
                    break
            
            if category is None or prompt_index is None:
                continue  # Orphaned ID, skip
            
            saved_data = self.prompts_data[category][prompt_index]
            # Check for actual changes
            if (pending_data.get("text") != saved_data.get("text") or
                pending_data.get("provider") != saved_data.get("provider") or
                pending_data.get("model") != saved_data.get("model") or
                pending_data.get("max_tokens") != saved_data.get("max_tokens") or
                pending_data.get("temperature") != saved_data.get("temperature")):
                
                self.prompts_data[category][prompt_index].update(pending_data)
                # Update tree item if it's the current (or find it to update tooltip/data)
                if self.current_prompt_item and self.current_prompt_item.data(0, Qt.UserRole).get("id") == prompt_id:
                    self.current_prompt_item.setData(0, Qt.UserRole, pending_data.copy())
                    self.current_prompt_item.setToolTip(0, self._create_prompt_tooltip(pending_data))
                updated = True
            
            del self.pending_changes[prompt_id]
    
        if updated:
            self._save_to_file()

    def _update_prompt_in_data(self, category: str, data: Dict) -> None:
        """Update prompt in prompts_data by ID."""
        for prompt in self.prompts_data.get(category, []):
            if prompt.get("id") == data.get("id"):
                prompt.update(data)
                break

    def _save_to_file(self) -> bool:
        """Save prompts_data to file and backup."""
        return save_prompts(self.prompts_data, self.prompts_file, self.backup_file)

    def _create_prompt_tooltip(self, prompt: Dict) -> str:
        """Create a tooltip string for a prompt."""
        if prompt.get("default", False):
            active_provider = WWSettingsManager.get_active_llm_name()
            active_config = WWSettingsManager.get_active_llm_config() or {}
            active_model = active_config.get("model", "Unknown")
            tooltip = (
                f"Provider: {active_provider}\n"
                f"Model: {active_model}\n"
                f"Max Tokens: {prompt.get('max_tokens', 2000)}\n"
                f"Temperature: {prompt.get('temperature', 0.7)}\n"
                f"Text: {prompt.get('text', '')}\n"
                f"Default prompt (read-only): Uses default LLM settings."
            )
        else:
            tooltip = (
                f"Provider: {prompt.get('provider', WWSettingsManager.get_active_llm_name())}\n"
                f"Model: {prompt.get('model', WWSettingsManager.get_active_llm_config().get('model', 'Unknown'))}\n"
                f"Max Tokens: {prompt.get('max_tokens', 2000)}\n"
                f"Temperature: {prompt.get('temperature', 0.7)}\n"
                f"Text: {prompt.get('text', '')}"
            )
        return tooltip

    def _get_provider_config(self) -> str:
        """Get the current provider configuration."""
        provider_index = self.provider_combo.currentIndex()
        provider_config = self.provider_combo.itemData(provider_index)
        return provider_config if isinstance(provider_config, str) else provider_config.get("provider", WWSettingsManager.get_active_llm_name())

    def _on_tree_context_menu(self, pos: 'QPoint') -> None:
        """Handle context menu for tree items."""
        item = self.tree.itemAt(pos)
        if not item:
            return
        
        data = item.data(0, Qt.UserRole)
        menu = QMenu()
        
        if data.get("type") != "category":
            menu.addAction(_("Replicate"), lambda: self._replicate_prompt())
        if data.get("type") == "prompt" and not data.get("default", False):
            menu.addAction(_("Rename"), lambda: self._rename_prompt(item))
            menu.addAction(_("Move Up"), lambda: self._move_prompt(item, up=True))
            menu.addAction(_("Move Down"), lambda: self._move_prompt(item, up=False))
            menu.addAction(_("Delete"), lambda: self._delete_prompt(item))
        
        if menu.actions():
            menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _add_new_prompt(self, category_item: QTreeWidgetItem) -> None:
        """Add a new prompt to the specified category."""
        category_name = category_item.data(0, Qt.UserRole).get("name")
        name, ok = QInputDialog.getText(self, _("New Prompt"), _("Enter prompt name:"))
        
        if not ok or not name.strip():
            return
        
        name = name.strip()
        # Check for duplicate name in the same category
        for prompt in self.prompts_data.get(category_name, []):
            if prompt.get("name").lower() == name.lower():
                QMessageBox.warning(self, _("Duplicate Prompt Name"),
                                   _("A prompt named '{}' already exists in category '{}'. Please choose a different name.").format(name, category_name))
                return
        
        new_id = str(uuid.uuid4())
        new_prompt = {
            "name": name,
            "text": "",
            "default": False,
            "provider": self._get_provider_config(),
            "model": self.model_combo.currentText(),
            "max_tokens": 2000,
            "temperature": 0.7,
            "type": "prompt",
            "id": new_id
        }
        
        self.prompts_data.setdefault(category_name, []).append(new_prompt)
        child = QTreeWidgetItem(category_item, [name])
        child.setData(0, Qt.UserRole, new_prompt)
        category_item.setExpanded(True)
        self.tree.setCurrentItem(child)
        self._save_to_file()

    def _rename_prompt(self, item: QTreeWidgetItem) -> None:
        """Rename a prompt."""
        data = item.data(0, Qt.UserRole)
        if data.get("default", False):
            QMessageBox.information(self, _("Rename Prompt"), _("Default prompts cannot be renamed."))
            return
        
        current_name = data.get("name")
        category = item.parent().text(0)
        new_name, ok = QInputDialog.getText(self, _("Rename Prompt"), _("Enter new prompt name:"), text=current_name)
        
        if not ok or not new_name.strip():
            return
        
        new_name = new_name.strip()
        # Check for duplicate name in the same category
        for prompt in self.prompts_data.get(category, []):
            if prompt.get("name").lower() == new_name.lower() and prompt.get("id") != data.get("id"):
                QMessageBox.warning(self, _("Duplicate Prompt Name"),
                                   _("A prompt named '{}' already exists in category '{}'. Please choose a different name.").format(new_name, category))
                return
        
        data["name"] = new_name
        item.setText(0, new_name)
        item.setData(0, Qt.UserRole, data)
        self._update_prompt_in_data(category, data)
        self._save_to_file()

    def _move_prompt(self, item: QTreeWidgetItem, up: bool = True) -> None:
        """Move a prompt up or down within its category."""
        data = item.data(0, Qt.UserRole)
        if data.get("default", False):
            QMessageBox.information(self, _("Move Prompt"), _("Default prompts cannot be moved."))
            return
        
        parent = item.parent()
        if not parent:
            return
        
        index = parent.indexOfChild(item)
        new_index = index - 1 if up else index + 1
        if new_index < 0 or new_index >= parent.childCount():
            return
        
        parent.takeChild(index)
        parent.insertChild(new_index, item)
        category = parent.text(0)
        prompts = self.prompts_data.get(category, [])
        if index < len(prompts) and new_index < len(prompts):
            prompts.insert(new_index, prompts.pop(index))
        self._save_to_file()

    def _delete_prompt(self, item: QTreeWidgetItem) -> None:
        """Delete a prompt."""
        data = item.data(0, Qt.UserRole)
        if data.get("default", False):
            QMessageBox.information(self, _("Delete Prompt"), _("Default prompts cannot be deleted."))
            return
        
        name = data.get("name")
        parent = item.parent()
        if not parent:
            return
        
        category = parent.text(0)
        reply = QMessageBox.question(self, _("Delete Prompt"), _("Delete prompt '{}'?").format(name),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            prompt_id = data.get("id")
            if prompt_id in self.pending_changes:
                del self.pending_changes[prompt_id]
            prompts = self.prompts_data.get(category, [])
            for i, prompt in enumerate(prompts):
                if prompt.get("id") == data.get("id"):
                    del prompts[i]
                    break
            parent.removeChild(item)
            self._save_to_file()

    def _replicate_prompt(self) -> None:
        """Replicate the current prompt."""
        if not self.current_prompt_item:
            return
        
        data = self.current_prompt_item.data(0, Qt.UserRole)
        if not data:
            return
        
        new_name, ok = QInputDialog.getText(
            self, _("Replicate Prompt"),
            _("Enter name for the new prompt:"),
            text=data.get("name") + " Copy"
        )
        
        if not ok or not new_name.strip():
            return
        
        new_name = new_name.strip()
        new_prompt = data.copy()
        new_prompt.update({"name": new_name, "default": False, "id": str(uuid.uuid4())})

        parent_item = self.current_prompt_item.parent()
        if parent_item:
            category = parent_item.text(0)
            self.prompts_data.setdefault(category, []).append(new_prompt)
            new_child = QTreeWidgetItem(parent_item, [new_name])
            new_child.setData(0, Qt.UserRole, new_prompt)
            new_child.setToolTip(0, self._create_prompt_tooltip(new_prompt))
            parent_item.setExpanded(True)
            self.tree.setCurrentItem(new_child)
            self._save_to_file()
            QMessageBox.information(self, _("Replicated"), _("Prompt replicated."))

    def _show_provider_info(self) -> None:
        """Show the provider information dialog."""
        dialog = ProviderInfoDialog(self)
        dialog.exec_()

    def _handle_plus_clicked(self, item: QTreeWidgetItem) -> None:
        """Handle plus button clicks for replicating prompts."""
        data = item.data(0, Qt.UserRole)
        if data.get("type") == "category":
            self._add_new_prompt(item)
        else:  # This feature was removed - too many icons on the screen
            self._replicate_prompt()
            
    def closeEvent(self, a0):
        self._update_pending_changes()  # Capture any unsaved editor text
        self._apply_pending_changes()   # Save to prompts_data and file
        super().closeEvent(a0)