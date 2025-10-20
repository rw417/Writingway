"""
Preview Editable Widget - Displays prompt configuration in an editable tree format.
Does NOT evaluate variables. Used in the tabbed tweak interface.
"""

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QComboBox,
    QPushButton,
    QHBoxLayout,
    QLabel,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from copy import deepcopy
from functools import partial

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s


class PreviewEditableWidget(QWidget):
    """
    Widget for editing prompt configuration directly.
    Shows the prompt structure in a tree without evaluating variables.
    """
    
    # Signal emitted when content is edited
    contentEdited = pyqtSignal()

    ROLE_OPTIONS = [
        ("User", "user"),
        ("Assistant", "assistant"),
        ("System", "system"),
        ("Tool", "tool"),
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.prompt_config = None
        self.message_widgets = []
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setRootIsDecorated(False)
        # Allow Shift/Ctrl multi-selection and provide Ctrl+A select all
        try:
            from PyQt5.QtWidgets import QAbstractItemView, QShortcut
            from PyQt5.QtGui import QKeySequence
            self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
            sc = QShortcut(QKeySequence("Ctrl+A"), self.tree)
            sc.activated.connect(lambda: self._select_all_in_tree(self.tree))
        except Exception:
            pass
        # Prefer per-pixel scrolling and a smaller single-step to avoid per-item jumps
        try:
            self.tree.setVerticalScrollMode(QTreeWidget.ScrollPerPixel)
            self.tree.verticalScrollBar().setSingleStep(12)
        except Exception:
            pass
        layout.addWidget(self.tree)

        self.add_message_button = QPushButton(_("Add Message"))
        self.add_message_button.setToolTip(_("Append a new message to the prompt"))
        self.add_message_button.clicked.connect(self.add_message)
        layout.addWidget(self.add_message_button)
    
    def set_prompt_config(self, prompt_config):
        """
        Set the prompt configuration to display and edit.
        
        Args:
            prompt_config (dict): The prompt configuration dict
        """
        self.prompt_config = deepcopy(prompt_config) if prompt_config else None
        if self.prompt_config is not None:
            messages = self.prompt_config.setdefault("messages", [])
            if not messages:
                messages.append({"role": "system", "content": ""})
        self.populate_tree()
    
    def populate_tree(self):
        """Populate the tree with the prompt configuration."""
        self.tree.clear()
        self.message_widgets = []

        has_config = bool(self.prompt_config)
        self.add_message_button.setEnabled(has_config)
        
        if not self.prompt_config:
            return
        
        messages = self.prompt_config.get("messages", [])
        
        for i, message in enumerate(messages):
            role = message.get("role", "unknown")
            content = message.get("content", "")
            
            # Create container widget for header and editor
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(8, 4, 8, 12)
            container_layout.setSpacing(6)

            header_layout = QHBoxLayout()
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(8)

            header_label = QLabel(f"{role.capitalize()} {_('Message')}")
            header_font = QFont()
            header_font.setBold(True)
            header_label.setFont(header_font)
            header_layout.addWidget(header_label)

            role_combo = None
            delete_button = None
            if i > 0:
                delete_button = QPushButton(_("Delete"))
                delete_button.setMaximumWidth(80)
                delete_button.clicked.connect(partial(self.delete_message, i))
                header_layout.addWidget(delete_button)

                role_combo = self._create_role_combo(role)
                role_combo.currentIndexChanged.connect(partial(self.on_role_changed, i))
                header_layout.addWidget(role_combo)

            header_layout.addStretch()
            container_layout.addLayout(header_layout)

            text_edit = QTextEdit()
            text_edit.setPlainText(content)
            text_edit.setMinimumHeight(100)
            # Reduce child text edits' scrollbar single-step for smoother wheel scrolling
            try:
                text_edit.verticalScrollBar().setSingleStep(12)
            except Exception:
                pass
            text_edit.textChanged.connect(partial(self.on_content_edited, i))
            container_layout.addWidget(text_edit)

            header_item = QTreeWidgetItem()
            header_item.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(header_item)
            self.tree.setItemWidget(header_item, 0, container)

            self.message_widgets.append(
                {
                    "text_edit": text_edit,
                    "role_combo": role_combo,
                    "header_label": header_label,
                    "delete_button": delete_button,
                }
            )
    
    def _create_role_combo(self, role):
        combo = QComboBox()
        combo.setMinimumWidth(120)
        existing_values = set()
        for label, value in self.ROLE_OPTIONS:
            combo.addItem(_(label), value)
            existing_values.add(value)

        normalized_role = (role or "user").lower()
        if normalized_role not in existing_values:
            combo.addItem(normalized_role.capitalize(), normalized_role)

        index = combo.findData(normalized_role)
        combo.setCurrentIndex(index if index >= 0 else combo.findData("user"))
        return combo

    def add_message(self):
        """Append a new message to the prompt configuration."""
        if self.prompt_config is None:
            self.prompt_config = {"messages": []}

        messages = self.prompt_config.setdefault("messages", [])
        messages.append({"role": "user", "content": ""})
        self.populate_tree()

        if self.message_widgets:
            self.message_widgets[-1]["text_edit"].setFocus()

        self.contentEdited.emit()

    def delete_message(self, message_index):
        """Remove a message from the prompt configuration."""
        if not self.prompt_config:
            return

        messages = self.prompt_config.get("messages", [])
        if message_index <= 0 or message_index >= len(messages):
            return

        del messages[message_index]

        if not messages:
            messages.append({"role": "system", "content": ""})

        next_focus_index = min(message_index - 1, len(messages) - 1)
        self.populate_tree()

        if 0 <= next_focus_index < len(self.message_widgets):
            self.message_widgets[next_focus_index]["text_edit"].setFocus()

        self.contentEdited.emit()

    def on_content_edited(self, message_index):
        """Called when a message content is edited."""
        if not self.prompt_config or message_index >= len(self.message_widgets):
            return

        messages = self.prompt_config.setdefault("messages", [])
        while len(messages) <= message_index:
            messages.append({"role": "user", "content": ""})

        text_edit = self.message_widgets[message_index]["text_edit"]
        messages[message_index]["content"] = text_edit.toPlainText()
        self.contentEdited.emit()

    def on_role_changed(self, message_index):
        """Called when a message role is changed via the combo box."""
        if (
            not self.prompt_config
            or message_index >= len(self.message_widgets)
            or not self.message_widgets[message_index].get("role_combo")
        ):
            return

        combo = self.message_widgets[message_index]["role_combo"]
        new_role = combo.currentData()

        messages = self.prompt_config.setdefault("messages", [])
        while len(messages) <= message_index:
            messages.append({"role": "user", "content": ""})

        messages[message_index]["role"] = new_role

    def _select_all_in_tree(self, tree_widget):
        try:
            root = tree_widget.invisibleRootItem()
            def recurse(parent):
                for i in range(parent.childCount()):
                    child = parent.child(i)
                    if not child.isHidden():
                        child.setSelected(True)
                    recurse(child)
            recurse(root)
        except Exception:
            pass

        header_label = self.message_widgets[message_index].get("header_label")
        if header_label and new_role:
            header_label.setText(f"{new_role.capitalize()} {_('Message')}")

        self.contentEdited.emit()
    
    def get_edited_config(self):
        """
        Get the edited prompt configuration.
        
        Returns:
            dict: The modified prompt configuration
        """
        if not self.prompt_config:
            return None
        
        config = deepcopy(self.prompt_config)
        config_messages = config.setdefault("messages", [])

        # Trim or expand message list to align with UI
        if len(config_messages) > len(self.message_widgets):
            config_messages = config_messages[: len(self.message_widgets)]
            config["messages"] = config_messages
        while len(config_messages) < len(self.message_widgets):
            config_messages.append({"role": "user", "content": ""})

        for idx, widget in enumerate(self.message_widgets):
            text_edit = widget["text_edit"]
            role_combo = widget.get("role_combo")
            config_messages[idx]["content"] = text_edit.toPlainText()

            if role_combo:
                config_messages[idx]["role"] = role_combo.currentData()

        return config
