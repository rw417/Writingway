from PyQt5.QtWidgets import QWidget, QTreeWidgetItem, QTextEdit, QShortcut, QMessageBox, QComboBox, QHBoxLayout, QPushButton, QVBoxLayout
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence
from settings.theme_manager import ThemeManager
import muse.prompt_handler as prompt_handler
import tiktoken
from PyQt5 import uic

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s

class PreviewWidget(QWidget):
    """Widget for previewing and editing prompt messages before sending."""
    
    # Signal emitted when user wants to send the prompt
    sendPromptRequested = pyqtSignal(dict)  # Emits modified prompt config
    # Signal emitted when user closes/returns
    returnRequested = pyqtSignal()
    
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        uic.loadUi("ui_files/dialogs/preview_widget.ui", self)
        self.controller = controller
        self.font_size = 12
        self.conversation_payload = None
        self.prompt_config = None
        self.user_input = None
        self.additional_vars = None
        self.current_scene_text = None
        self.extra_context = None
        self.final_prompt_text = ""
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize UI components."""
        # Set up icons and tooltips for zoom buttons
        self.zoom_in_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/zoom-in.svg", self.controller.icon_tint))
        self.zoom_in_button.setToolTip(_("Zoom In (Ctrl+=)"))
        self.zoom_in_button.clicked.connect(self.zoom_in)

        self.zoom_out_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/zoom-out.svg", self.controller.icon_tint))
        self.zoom_out_button.setToolTip(_("Zoom Out (Ctrl+-)"))
        self.zoom_out_button.clicked.connect(self.zoom_out)

        self.ok_button.clicked.connect(lambda: self.returnRequested.emit())
        
        # Set up send prompt button
        self.send_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg", self.controller.icon_tint))
        self.send_prompt_button.setToolTip(_("Send prompt to LLM"))
        self.send_prompt_button.clicked.connect(self.send_prompt_to_llm)
        
        # Set up add message button
        self.add_message_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/plus.svg", self.controller.icon_tint))
        self.add_message_button.setToolTip(_("Add new message"))
        self.add_message_button.clicked.connect(self.add_new_message)

        # Set tree to 1 column
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)

        # Shortcuts for zoom
        self.zoom_in_shortcut = QShortcut(QKeySequence("Ctrl+="), self)
        self.zoom_in_shortcut.activated.connect(self.zoom_in)
        self.zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        self.zoom_out_shortcut.activated.connect(self.zoom_out)

        # Set initial font size
        self.update_font_size()
    
    def set_prompt_data(self, conversation_payload=None, prompt_config=None, user_input=None,
                       additional_vars=None, current_scene_text=None, extra_context=None):
        """Set the prompt data to display."""
        self.conversation_payload = conversation_payload
        self.prompt_config = prompt_config
        self.user_input = user_input
        self.additional_vars = additional_vars
        self.current_scene_text = current_scene_text
        self.extra_context = extra_context
    
    def refresh_preview(self, tweak_overrides=None):
        """
        Refresh the preview with current prompt data.
        
        Args:
            tweak_overrides (dict): Optional dict of tweak values to merge into additional_vars
        """
        # Merge tweak overrides into additional_vars if provided
        if tweak_overrides:
            if self.additional_vars is None:
                self.additional_vars = {}
            self.additional_vars.update(tweak_overrides)
        
        self.populate_tree()
        self.update_token_count()
    
    def populate_tree(self):
        """Populate the tree widget with message content."""
        self.tree.clear()
        if self.conversation_payload:
            sections = self.parse_conversation_payload()
        else:
            messages_list = prompt_handler.assemble_final_prompt(
                self.prompt_config, self.user_input, self.additional_vars,
                self.current_scene_text, self.extra_context
            )
            sections = self.parse_messages_list(messages_list)
            self.final_prompt_text = "\n\n".join(msg.get("content", "") for msg in messages_list)

        for i, (header, content) in enumerate(sections.items()):
            # First message is always system role, no role selector needed
            is_system_message = i == 0 or "system" in header.lower()
            
            header_item = QTreeWidgetItem(self.tree)
            # Set header text based on message type
            if is_system_message:
                header_item.setText(0, "Message: System")
            else:
                # Create custom header widget for non-system messages
                from PyQt5.QtWidgets import QLabel
                header_widget = QWidget()
                header_layout = QHBoxLayout(header_widget)
                header_layout.setContentsMargins(0, 0, 0, 0)
                
                # Add "Message: " label
                message_label = QLabel("Message: ")
                message_label.setFont(QFont("Arial", self.font_size, QFont.Bold))
                header_layout.addWidget(message_label)
                
                # Role selector for non-system messages
                role_combo = QComboBox()
                role_combo.addItems(["User", "Assistant"])
                # Extract role from header and set default
                if "assistant" in header.lower():
                    role_combo.setCurrentText("Assistant")
                else:
                    role_combo.setCurrentText("User")
                role_combo.currentTextChanged.connect(self.update_token_count_from_edited_content)
                header_layout.addWidget(role_combo)
                
                # Delete button
                delete_button = QPushButton("Delete")
                delete_button.setMaximumWidth(80)
                delete_button.clicked.connect(lambda checked, item=header_item: self.delete_message(item))
                header_layout.addWidget(delete_button)
                
                # Add stretch
                header_layout.addStretch()
                
                self.tree.setItemWidget(header_item, 0, header_widget)
                header_item.setText(0, "")  # Clear text since we're using widget
            
            header_item.setFont(0, QFont("Arial", self.font_size, QFont.Bold))

            content_item = QTreeWidgetItem(header_item)
            
            # Create container widget for text edit
            container_widget = QWidget()
            container_layout = QVBoxLayout(container_widget)
            container_layout.setContentsMargins(0, 0, 0, 0)
            
            # Text edit
            text_edit = QTextEdit()
            text_edit.setReadOnly(False)  # Make editable
            text_edit.setPlainText(content)
            text_edit.setFont(QFont("Arial", self.font_size))
            text_edit.setStyleSheet("QTextEdit { border: 1px solid #ccc; padding: 4px; }")
            # Connect text change to token count update
            text_edit.textChanged.connect(self.update_token_count_from_edited_content)
            
            container_layout.addWidget(text_edit)
            
            self.tree.setItemWidget(content_item, 0, container_widget)
            
            # Store references for easy access
            if is_system_message:
                header_item.setData(0, Qt.UserRole, {
                    'text_edit': text_edit,
                    'is_system': True,
                    'role_combo': None,
                    'delete_button': None
                })
            else:
                header_item.setData(0, Qt.UserRole, {
                    'text_edit': text_edit,
                    'is_system': False,
                    'role_combo': role_combo,
                    'delete_button': delete_button
                })

            if len(content.strip()) > 1000:
                header_item.setExpanded(False)
            else:
                header_item.setExpanded(True)

        self.tree.expandAll()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            data = item.data(0, Qt.UserRole)
            if data and 'text_edit' in data:
                text_edit = data['text_edit']
                content_length = len(text_edit.toPlainText().strip())
                maxheight = min(max(2, int(content_length / 50)), 50) * 30
                text_edit.setMaximumHeight(maxheight)
                if content_length > 1000:
                    item.setExpanded(False)
            self.tree.resizeColumnToContents(0)

    def parse_conversation_payload(self):
        """Parse conversation payload into sections."""
        sections = {}
        self.final_prompt_text = ""
        for i, message in enumerate(self.conversation_payload):
            role = message.get("role", "unknown").capitalize()
            content = message.get("content", "")
            header = f"Message {i + 1}: {role}"
            sections[header] = content
            self.final_prompt_text += content + "\n"
        if not sections:
            sections["Empty"] = "No content available"
        return sections

    def parse_messages_list(self, messages_list):
        """Parse messages list into sections."""
        sections = {}
        for i, message in enumerate(messages_list):
            if not isinstance(message, dict):
                continue
            role = message.get("role", "unknown").capitalize()
            content = message.get("content", "")
            header = f"Message {i + 1}: {role}"
            sections[header] = content
        if not sections:
            sections["Empty"] = "No content available"
        return sections

    def zoom_in(self):
        """Increase font size."""
        if self.font_size < 24:
            self.font_size += 2
            self.update_font_size()

    def zoom_out(self):
        """Decrease font size."""
        if self.font_size > 8:
            self.font_size -= 2
            self.update_font_size()

    def update_font_size(self):
        """Update font size for all UI elements."""
        for i in range(self.tree.topLevelItemCount()):
            header_item = self.tree.topLevelItem(i)
            header_item.setFont(0, QFont("Arial", self.font_size, QFont.Bold))
            if header_item.childCount() > 0:
                data = header_item.data(0, Qt.UserRole)
                if data and 'text_edit' in data:
                    text_edit = data['text_edit']
                    text_edit.setFont(QFont("Arial", self.font_size))
        self.token_count_label.setFont(QFont("Arial", self.font_size))
    
    def delete_message(self, header_item):
        """Delete a message from the tree."""
        data = header_item.data(0, Qt.UserRole)
        if data and data.get('is_system', False):
            QMessageBox.warning(self, _("Cannot Delete"), _("Cannot delete the system message."))
            return
            
        if self.tree.topLevelItemCount() <= 1:
            QMessageBox.warning(self, _("Cannot Delete"), _("Cannot delete the last remaining message."))
            return
        
        reply = QMessageBox.question(self, _("Delete Message"), _("Are you sure you want to delete this message?"),
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            index = self.tree.indexOfTopLevelItem(header_item)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
                self.update_token_count_from_edited_content()
    
    def add_new_message(self):
        """Add a new message to the tree."""
        content = ""
        
        header_item = QTreeWidgetItem(self.tree)
        
        # Create custom header widget for new message
        from PyQt5.QtWidgets import QLabel
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Add "Message: " label
        message_label = QLabel("Message: ")
        message_label.setFont(QFont("Arial", self.font_size, QFont.Bold))
        header_layout.addWidget(message_label)
        
        # Role selector
        role_combo = QComboBox()
        role_combo.addItems(["User", "Assistant"])
        role_combo.setCurrentText("User")  # Default to User
        role_combo.currentTextChanged.connect(self.update_token_count_from_edited_content)
        header_layout.addWidget(role_combo)
        
        # Delete button
        delete_button = QPushButton("Delete")
        delete_button.setMaximumWidth(80)
        delete_button.clicked.connect(lambda checked: self.delete_message(header_item))
        header_layout.addWidget(delete_button)
        
        # Add stretch
        header_layout.addStretch()
        
        self.tree.setItemWidget(header_item, 0, header_widget)
        header_item.setText(0, "")  # Clear text since we're using widget
        header_item.setFont(0, QFont("Arial", self.font_size, QFont.Bold))
        
        content_item = QTreeWidgetItem(header_item)
        
        # Create container widget for text edit
        container_widget = QWidget()
        container_layout = QVBoxLayout(container_widget)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Text edit
        text_edit = QTextEdit()
        text_edit.setReadOnly(False)
        text_edit.setPlainText(content)
        text_edit.setFont(QFont("Arial", self.font_size))
        text_edit.setStyleSheet("QTextEdit { border: 1px solid #ccc; padding: 4px; }")
        text_edit.textChanged.connect(self.update_token_count_from_edited_content)
        
        container_layout.addWidget(text_edit)
        self.tree.setItemWidget(content_item, 0, container_widget)
        
        # Store references for easy access
        header_item.setData(0, Qt.UserRole, {
            'text_edit': text_edit,
            'is_system': False,
            'role_combo': role_combo,
            'delete_button': delete_button
        })
        
        header_item.setExpanded(True)
        text_edit.setFocus()  # Focus the new text edit
        self.update_token_count_from_edited_content()

    def get_edited_content(self):
        """Collect all edited content from the text boxes in the tree."""
        edited_messages = []
        for i in range(self.tree.topLevelItemCount()):
            header_item = self.tree.topLevelItem(i)
            if header_item.childCount() > 0:
                data = header_item.data(0, Qt.UserRole)
                if data and 'text_edit' in data:
                    text_edit = data['text_edit']
                    is_system = data.get('is_system', False)
                    role_combo = data.get('role_combo')
                    content = text_edit.toPlainText()
                    
                    # Determine role
                    if is_system:
                        role = "system"
                    elif role_combo:
                        selected_role = role_combo.currentText().lower()
                        if selected_role == "assistant":
                            role = "assistant"
                        else:
                            role = "user"
                    else:
                        role = "user"
                    
                    edited_messages.append({
                        "role": role,
                        "content": content
                    })
        return edited_messages
    
    def update_token_count_from_edited_content(self):
        """Update token count based on currently edited content."""
        try:
            # Get current edited content
            edited_messages = self.get_edited_content()
            combined_text = "\n\n".join(msg["content"] for msg in edited_messages)
            
            encoding = tiktoken.get_encoding("cl100k_base")
            tokens = encoding.encode(combined_text)
            token_count = len(tokens)
            self.token_count_label.setText(_("Token Count: {}").format(token_count))
        except Exception as e:
            self.token_count_label.setText(_("Token Count: Error ({})").format(str(e)))
    
    def update_token_count(self):
        """Update token count based on final prompt text."""
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            tokens = encoding.encode(self.final_prompt_text)
            token_count = len(tokens)
            self.token_count_label.setText(_("Token Count: {}").format(token_count))
        except Exception as e:
            self.token_count_label.setText(_("Token Count: Error ({})").format(str(e)))

    def send_prompt_to_llm(self):
        """Send the currently edited prompt by emitting signal."""
        # Get the edited content from all text boxes
        edited_messages = self.get_edited_content()
        
        if not edited_messages:
            QMessageBox.warning(self, _("No Content"), _("No content available to send."))
            return
        
        # Use the original prompt config if available, otherwise create a basic one
        if self.prompt_config:
            # Make a copy of the original config to preserve all settings
            modified_config = self.prompt_config.copy()
        else:
            # Create a basic config with default settings
            modified_config = {
                "provider": "Local",
                "model": "Local Model"
            }
        
        # Replace the "messages" field with our edited content
        modified_config["messages"] = edited_messages
        
        # Emit signal with the modified config
        self.sendPromptRequested.emit(modified_config)
