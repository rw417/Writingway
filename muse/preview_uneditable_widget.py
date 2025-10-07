"""
Preview Uneditable Widget - Displays the fully assembled prompt with variables evaluated.
Read-only view. Shows the final prompt that will be sent to the LLM.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QTextEdit, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from muse.prompt_handler import assemble_final_prompt
import tiktoken

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s


class PreviewUneditableWidget(QWidget):
    """
    Widget for previewing the final assembled prompt.
    Shows the prompt with all variables evaluated in read-only format.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        layout.addWidget(self.tree)
        
        # Token count label
        self.token_label = QLabel(_("Token Count: 0"))
        self.token_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.token_label)
    
    def set_prompt_data(self, prompt_config, user_input="", additional_vars=None, 
                       current_scene_text="", extra_context=None):
        """
        Assemble and display the final prompt.
        
        Args:
            prompt_config (dict): The prompt configuration
            user_input (str): User input text (action beats)
            additional_vars (dict): Additional variables for substitution
            current_scene_text (str): Current scene text
            extra_context (dict): Extra context data
        """
        if not prompt_config:
            self.tree.clear()
            self.token_label.setText(_("Token Count: 0"))
            return
        
        # Assemble the prompt with all variables
        try:
            # assemble_final_prompt returns a list of message dicts directly
            messages = assemble_final_prompt(
                prompt_config=prompt_config,
                user_input=user_input,
                additional_vars=additional_vars or {},
                current_scene_text=current_scene_text,
                extra_context=extra_context
            )
            
            self.populate_tree(messages)
            self.update_token_count(messages)
            
        except Exception as e:
            self.tree.clear()
            error_item = QTreeWidgetItem([f"Error assembling prompt: {str(e)}"])
            self.tree.addTopLevelItem(error_item)
            self.token_label.setText(_("Token Count: Error"))
            import traceback
            traceback.print_exc()
    
    def populate_tree(self, messages):
        """Populate the tree with the assembled prompt."""
        self.tree.clear()
        
        if not messages:
            return
        
        for i, message in enumerate(messages):
            role = message.get("role", "unknown")
            content = message.get("content", "")
            
            # Create header item
            header_text = f"{role.capitalize()} Message"
            header_item = QTreeWidgetItem([header_text])
            header_font = QFont()
            header_font.setBold(True)
            header_item.setFont(0, header_font)
            self.tree.addTopLevelItem(header_item)
            
            # Create read-only text display for content
            content_item = QTreeWidgetItem(header_item, [""])
            text_display = QTextEdit()
            text_display.setPlainText(content)
            text_display.setReadOnly(True)
            text_display.setMinimumHeight(100)
            self.tree.setItemWidget(content_item, 0, text_display)
        
        self.tree.expandAll()
    
    def update_token_count(self, messages):
        """Update the token count label."""
        try:
            # Count tokens from all messages
            encoding = tiktoken.get_encoding("cl100k_base")
            total_tokens = 0
            
            for message in messages:
                content = message.get("content", "")
                tokens = encoding.encode(content)
                total_tokens += len(tokens)
            
            self.token_label.setText(_("Token Count: {}").format(total_tokens))
        except Exception as e:
            self.token_label.setText(_("Token Count: Unknown"))
