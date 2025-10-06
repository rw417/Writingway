from PyQt5.QtWidgets import QDialog, QTreeWidgetItem, QTextEdit, QShortcut
from PyQt5.QtCore import Qt, QSettings
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

class PromptPreviewDialog(QDialog):
    def __init__(self, controller, conversation_payload=None, prompt_config=None, user_input=None, 
                 additional_vars=None, current_scene_text=None, extra_context=None, parent=None):
        super().__init__(parent)
        uic.loadUi("ui_files/dialogs/prompt_preview_dialog.ui", self)
        self.controller = controller
        self.conversation_payload = conversation_payload
        self.prompt_config = prompt_config
        self.user_input = user_input
        self.additional_vars = additional_vars
        self.current_scene_text = current_scene_text
        self.extra_context = extra_context
        self.font_size = 12  # Default font size in points
        self.final_prompt_text = ""  # Store final prompt text for token counting
        self.setup_ui()
        self.read_settings()
        self.update_token_count()
        self.setMinimumSize(self.size())

    def setup_ui(self):
        # Set up icons and tooltips for zoom buttons
        self.zoom_in_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/zoom-in.svg", self.controller.icon_tint))
        self.zoom_in_button.setToolTip(_("Zoom In (Cmd+=)"))
        self.zoom_in_button.clicked.connect(self.zoom_in)

        self.zoom_out_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/zoom-out.svg", self.controller.icon_tint))
        self.zoom_out_button.setToolTip(_("Zoom Out (Cmd+-)"))
        self.zoom_out_button.clicked.connect(self.zoom_out)

        self.ok_button.clicked.connect(self.ok_button_clicked)

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
        # Populate the tree with dynamic content
        self.populate_tree()

    def populate_tree(self):
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

        for header, content in sections.items():
            header_item = QTreeWidgetItem(self.tree)
            header_item.setText(0, header)
            header_item.setFont(0, QFont("Arial", self.font_size, QFont.Bold))

            content_item = QTreeWidgetItem(header_item)
            # Place the QTextEdit in column 0
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(content)
            text_edit.setFont(QFont("Arial", self.font_size))
            text_edit.setStyleSheet("QTextEdit { border: 1px solid #ccc; padding: 4px; }")
            self.tree.setItemWidget(content_item, 0, text_edit)

            if len(content.strip()) > 1000:
                header_item.setExpanded(False)
            else:
                header_item.setExpanded(True)

        self.tree.expandAll()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            text_edit = self.tree.itemWidget(item.child(0), 0)
            content_length = len(text_edit.toPlainText().strip())
            maxheight = min(max(2, int(content_length / 50)), 50) * 30
            text_edit.setMaximumHeight(maxheight)
            if content_length > 1000:
                item.setExpanded(False)
            self.tree.resizeColumnToContents(0)

    def parse_conversation_payload(self):
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
        if self.font_size < 24:
            self.font_size += 2
            self.update_font_size()

    def zoom_out(self):
        if self.font_size > 8:
            self.font_size -= 2
            self.update_font_size()

    def update_font_size(self):
        for i in range(self.tree.topLevelItemCount()):
            header_item = self.tree.topLevelItem(i)
            header_item.setFont(0, QFont("Arial", self.font_size, QFont.Bold))
            content_widget = self.tree.itemWidget(header_item.child(0), 1)
            if content_widget:
                content_widget.setFont(QFont("Arial", self.font_size))
        self.token_count_label.setFont(QFont("Arial", self.font_size))

    def update_token_count(self):
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            tokens = encoding.encode(self.final_prompt_text)
            token_count = len(tokens)
            self.token_count_label.setText(_("Token Count: {}".format(token_count)))
        except Exception as e:
            self.token_count_label.setText(_("Token Count: Error ({})".format(str(e))))

    def read_settings(self):
        settings = QSettings("MyCompany", "WritingwayProject")
        geometry = settings.value("prompt_preview/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.font_size = settings.value("prompt_preview/fontSize", 12, type=int)
        self.update_font_size()

    def write_settings(self):
        settings = QSettings("MyCompany", "WritingwayProject")
        settings.setValue("prompt_preview/geometry", self.saveGeometry())
        settings.setValue("prompt_preview/fontSize", self.font_size)

    def closeEvent(self, event):
        self.write_settings()
        event.accept()

    def ok_button_clicked(self):
        self.write_settings()
        self.accept()
