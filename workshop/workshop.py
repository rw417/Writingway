import datetime
import tempfile
import pyaudio
import wave
import whisper
import json
import logging
import os
import re
from copy import deepcopy
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QMessageBox, QInputDialog, QFormLayout,
    QSplitter, QWidget, QLabel, QApplication, QListWidget, QListWidgetItem, 
    QMenu, QComboBox, QSizePolicy
)
from PyQt5.QtCore import Qt, QPoint, QThread, pyqtSignal, QTimer, QSettings, QCoreApplication
from PyQt5.QtGui import QCursor, QPixmap, QFont, QKeySequence, QTextCursor
from PyQt5.QtWidgets import QShortcut
from muse.prompt_panel import PromptPanel
from muse.prompt_preview_dialog import PromptPreviewDialog
from muse.prompt_handler import assemble_final_prompt
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager
from settings.llm_api_aggregator import WWApiAggregator
from settings.llm_worker import LLMWorker
from settings.autosave_manager import load_latest_autosave
from .chat_models import ChatMessage, clone_history_until, deserialize_messages, serialize_messages
from .chat_widgets import ChatListWidget
from .conversation_history_manager import estimate_conversation_tokens, summarize_conversation
from .embedding_manager import EmbeddingIndex
from compendium.context_panel import ContextPanel
from .rag_pdf import PdfRagApp

TOKEN_LIMIT = 2000


def _(text):
    return QCoreApplication.translate("WorkshopWindow", text)


class WorkshopWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Workshop"))
        flags = self.windowFlags()
        flags |= Qt.Window
        flags |= Qt.WindowMinimizeButtonHint
        flags |= Qt.WindowMaximizeButtonHint
        flags &= ~Qt.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
        self.controller = parent
        self.model = getattr(parent, "model", None) if parent else None
        self.project_name = getattr(self.model, "project_name", "DefaultProject") if parent else "DefaultProject"
        self.structure = getattr(self.model, "structure", {"acts": []}) if parent else {"acts": []}
        self.workshop_prompt_config = None
        self._is_initial_load = False  # Flag to prevent saving during initial load
        self.is_streaming = False  # Track streaming state
        self.worker = None  # LLMWorker instance
        self.pending_user_message_id = None
        self.streaming_message_id = None
        self.compendium_match_service = getattr(parent, "compendium_match_service", None)
        self._chat_match_highlighter = None

        # Conversation management
        self.conversation_history = []
        self.conversations = {}
        self.current_conversation = "Chat 1"
        self.conversations[self.current_conversation] = self.conversation_history
        self.pending_user_text = ""
        self.streaming_mode = None
        self.previous_variant_index = None
        self.streaming_variant_id = None

        # Initialize the embedding index for context retrieval
        self.embedding_index = EmbeddingIndex()

        self.current_mode = "Normal"
        
        # Audio recording variables
        self.pause_start = None
        self.available_models = self.get_available_models()

        # Define custom cursors for transcription
        self.waiting_cursor = QCursor(QPixmap("assets/icons/clock.svg"))
        self.normal_cursor = QCursor()

        # Font size for chat log
        self.font_size = 12  # Default font size

        self.init_ui()
        self.load_conversations()
        self.read_settings()

        if self.compendium_match_service and hasattr(self, "chat_input"):
            doc_id = f"{self.project_name}:workshop_chat"
            self._chat_match_highlighter = self.compendium_match_service.attach_highlighter(
                self.chat_input.document(), doc_id
            )

        # Connect model signal if available
        if self.model:
            self.model.structureChanged.connect(self.context_panel.on_structure_changed)

    def closeEvent(self, event):
        if self.compendium_match_service and self._chat_match_highlighter:
            self.compendium_match_service.detach_highlighter(self._chat_match_highlighter)
            self._chat_match_highlighter = None
        super().closeEvent(event)

    def get_available_models(self):
        cache_dir = os.path.expanduser("~/.cache/whisper")
        models = []
        if os.path.exists(cache_dir):
            for file in os.listdir(cache_dir):
                if file.endswith(".pt"):
                    model_name = file.split(".")[0]
                    models.append(model_name)
        return models or ["tiny"]

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 10, 0)

        # Outer splitter divides conversation list and chat panel
        self.outer_splitter = QSplitter(Qt.Horizontal)

        # Conversation History Panel
        conversation_container = QWidget()
        conversation_layout = QVBoxLayout(conversation_container)
        conversation_layout.setContentsMargins(0, 0, 0, 0)

        self.conversation_list = QListWidget()
        self.conversation_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conversation_list.customContextMenuRequested.connect(self.show_conversation_context_menu)
        self.conversation_list.itemSelectionChanged.connect(self.on_conversation_selection_changed)
        conversation_layout.addWidget(self.conversation_list)

        new_chat_button = QPushButton(_("New Chat"))
        new_chat_button.clicked.connect(self.new_conversation)
        conversation_layout.addWidget(new_chat_button)

        self.outer_splitter.addWidget(conversation_container)
        self.outer_splitter.setStretchFactor(0, 1)

        # Chat Panel
        chat_panel = QWidget()
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        # Chat log (display area)
        self.chat_list = ChatListWidget(self)
        self.update_chat_list_font()
        self.chat_list.swipe_requested.connect(self.handle_swipe_request)
        self.chat_list.prev_variant_requested.connect(self.handle_prev_variant)
        self.chat_list.next_variant_requested.connect(self.handle_next_variant)
        self.chat_list.branch_requested.connect(self.handle_branch_request)
        chat_layout.addWidget(self.chat_list)

        # Splitter for input and context panel
        self.inner_splitter = QSplitter(Qt.Horizontal)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText(_("Type your message here..."))
        self.chat_input.setFont(QFont("Arial", self.font_size))
        left_layout.addWidget(self.chat_input)

        # Buttons and Mode/Prompt Panel
        bottomrow_layout = QHBoxLayout()

        # Mode selection for FAISS vector search
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Normal", "Economy", "Ultra-Light"])
        self.mode_selector.currentIndexChanged.connect(self.mode_changed)

        # Prompt Panel
        self.prompt_panel = PromptPanel("Workshop")
        self.prompt_panel.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.prompt_panel.setMaximumWidth(300)
        bottomrow_layout.addWidget(self.prompt_panel)

        middle_stack = QFormLayout()
        button_row1 = QHBoxLayout()

        # Prompt Preview button
        self.preview_button = QPushButton()
        self.preview_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/eye.svg"))
        self.preview_button.setToolTip(_("Preview the final prompt"))
        self.preview_button.clicked.connect(self.preview_prompt)
        button_row1.addWidget(self.preview_button)

        # Send button
        self.send_button = QPushButton()
        self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg"))
        self.send_button.clicked.connect(self.on_send_or_stop)
        button_row1.addWidget(self.send_button)

        button_row2 = QHBoxLayout()

        # Context button
        self.context_button = QPushButton()
        self.context_button.setCheckable(True)
        self.context_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book-open.svg"))
        self.context_button.clicked.connect(self.toggle_context_panel)
        button_row2.addWidget(self.context_button)

        # PDF RAG Button
        self.pdf_rag_btn = QPushButton()
        self.pdf_rag_btn.setIcon(ThemeManager.get_tinted_icon("assets/icons/file-text.svg"))
        self.pdf_rag_btn.setToolTip("Document Analysis (PDF/Images)")
        self.pdf_rag_btn.clicked.connect(self.open_pdf_rag_tool)
        button_row2.addWidget(self.pdf_rag_btn)

        middle_stack.addRow(button_row1)
        middle_stack.addRow(button_row2)
        bottomrow_layout.addLayout(middle_stack)
        bottomrow_layout.addStretch()

        # Audio recording section
        audio_stack = QFormLayout()
        audio_stack.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        audio_group_layout = QHBoxLayout()
        
        self.record_button = QPushButton()
        self.record_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/mic.svg"))
        self.record_button.setCheckable(True)
        self.record_button.clicked.connect(self.toggle_recording)
        audio_group_layout.addWidget(self.record_button)
        
        self.pause_button = QPushButton()
        self.pause_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/pause.svg"))
        self.pause_button.setCheckable(True)
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_pause)
        audio_group_layout.addWidget(self.pause_button)
        audio_group_layout.addStretch()

        self.time_label = QLabel("00:00")
        audio_group_layout.addWidget(self.time_label)
        
        # Whisper model selection
        audio_model_label = QLabel(_("Speech Model: "))
        self.model_combo = QComboBox()
        self.model_combo.addItems(self.available_models)
        
        audio_lang_label = QLabel(_("Language: "))
        self.language_combo = QComboBox()
        self.language_combo.addItems([
            "Auto", "English", "Polish", "Spanish", "French", "German", 
            "Italian", "Portuguese", "Russian", "Japanese", "Chinese", 
            "Korean", "Dutch", "Arabic", "Hindi", "Swedish", "Czech", 
            "Finnish", "Turkish", "Greek", "Ukrainian"
        ])
        
        audio_stack.addRow(audio_group_layout)
        audio_stack.addRow(audio_model_label, self.model_combo)
        audio_stack.addRow(audio_lang_label, self.language_combo)
        bottomrow_layout.addItem(audio_stack)
        
        self.recording_timer = QTimer()
        self.recording_timer.timeout.connect(self.update_recording_time)

        left_layout.addLayout(bottomrow_layout)
        self.inner_splitter.addWidget(left_container)

        # Context Panel
        self.context_panel = ContextPanel(self.structure, self.project_name, parent=self)
        self.context_panel.setMinimumWidth(150)
        self.inner_splitter.addWidget(self.context_panel)
        self.inner_splitter.setSizes([500, 300])
        self._left_panel_last_width = 500
        self._context_panel_last_width = max(300, self.context_panel.minimumWidth())

        chat_layout.addWidget(self.inner_splitter)
        self.outer_splitter.addWidget(chat_panel)
        self.outer_splitter.setStretchFactor(1, 3)

        main_layout.addWidget(self.outer_splitter)
        
        # Shortcuts for zoom
        self.zoom_in_shortcut = QShortcut(QKeySequence("Ctrl+="), self)
        self.zoom_in_shortcut.activated.connect(self.zoom_in)
        self.zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        self.zoom_out_shortcut.activated.connect(self.zoom_out)

    def open_pdf_rag_tool(self):
        """Open the PDF RAG processor as independent window"""
        self.pdf_window = PdfRagApp()
        self.pdf_window.show()

    def read_settings(self):
        settings = QSettings("MyCompany", "WritingwayProject")
        geometry = settings.value("workshop_window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.font_size = settings.value("workshop_window/fontSize", 12, type=int)
        
        # Convert splitter sizes to integers
        outer_splitter_sizes = [int(size) for size in 
            settings.value("workshop_window/outer_splitter", [200, 800], type=list)]
        inner_splitter_sizes = [int(size) for size in 
            settings.value("workshop_window/inner_splitter", [500, 300], type=list)]
        
        self.chat_input.setFont(QFont("Arial", self.font_size))
        self.update_chat_list_font()
        self.outer_splitter.setSizes(outer_splitter_sizes)
        self.inner_splitter.setSizes(inner_splitter_sizes)
        if len(inner_splitter_sizes) >= 2:
            self._left_panel_last_width = max(inner_splitter_sizes[0], 0)
            self._context_panel_last_width = max(inner_splitter_sizes[1], self.context_panel.minimumWidth())

    def write_settings(self):
        settings = QSettings("MyCompany", "WritingwayProject")
        settings.setValue("workshop_window/geometry", self.saveGeometry())
        settings.setValue("workshop_window/fontSize", self.font_size)
        settings.setValue("workshop_window/outer_splitter", self.outer_splitter.sizes())
        settings.setValue("workshop_window/inner_splitter", self.inner_splitter.sizes())

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
        """Apply the current font size to chat bubbles and input."""
        self.chat_input.setFont(QFont("Arial", self.font_size))
        self.update_chat_list_font()

    def update_chat_list_font(self):
        if hasattr(self, "chat_list"):
            self.chat_list.setStyleSheet(f"QLabel {{ font-size: {self.font_size}pt; }}")

    def construct_message(self, *, allow_empty: bool = False):
        """Construct the conversation payload for the Workshop chat."""
        raw_user_message = self.chat_input.toPlainText()
        user_message = raw_user_message.strip()
        if not user_message and not allow_empty:
            return [], {}, None, []

        # Build augmented message with context selections and retrieved passages
        augmented_message = user_message if user_message else ""

        context_text = self.context_panel.get_selected_context_text()
        if context_text:
            if augmented_message:
                augmented_message += "\n\n"
            augmented_message += "Context:\n" + context_text

        retrieved_context = self.embedding_index.query(user_message) if user_message else []
        if retrieved_context:
            augmented_message += "\n[Retrieved Context]:\n" + "\n".join(retrieved_context)

        history_payload = []
        for message in self.conversation_history:
            if message.id == self.pending_user_message_id and message.role == "user":
                continue
            if message.id == self.streaming_message_id and not message.content.strip():
                continue
            payload_content = message.metadata.get("augmented_content", message.content) if message.role == "user" else message.content
            history_payload.append({"role": message.role, "content": payload_content})

        overrides = {}
        prompt_messages = []
        prompt_config = self.prompt_panel.get_prompt()
        if prompt_config:
            overrides = self.prompt_panel.get_overrides()
            prompt_messages = assemble_final_prompt(prompt_config, None) or []

        conversation_payload = []
        if prompt_messages:
            conversation_payload.extend(deepcopy(prompt_messages))
        conversation_payload.extend(history_payload)
        conversation_payload.append({"role": "user", "content": augmented_message})

        if estimate_conversation_tokens(conversation_payload) > TOKEN_LIMIT:
            summary = summarize_conversation(conversation_payload, overrides=overrides)
            conversation_payload = []
            if prompt_messages:
                conversation_payload.extend(deepcopy(prompt_messages))
            conversation_payload.append({"role": "user", "content": summary})

        return conversation_payload, overrides, prompt_config, prompt_messages

    def build_payload_for_history(self, messages, prompt_seed=None):
        payload = []

        if isinstance(prompt_seed, list):
            for entry in prompt_seed:
                if isinstance(entry, dict) and entry.get("content"):
                    payload.append({
                        "role": entry.get("role", "system"),
                        "content": entry.get("content", "")
                    })
        else:
            resolved_prompt = prompt_seed
            if resolved_prompt is None:
                prompt_config = self.prompt_panel.get_prompt()
                prompt_messages = assemble_final_prompt(prompt_config, None) if prompt_config else []
                if prompt_messages:
                    payload.extend(deepcopy(prompt_messages))
            elif isinstance(resolved_prompt, str) and resolved_prompt.strip():
                payload.append({"role": "system", "content": resolved_prompt})

        message_list = list(messages)
        for message in message_list:
            content = message.metadata.get("augmented_content", message.content) if message.role == "user" else message.content
            payload.append({"role": message.role, "content": content})

        return payload

    def preview_prompt(self):
        """Preview the full conversation payload sent to the LLM."""
        conversation_payload, _, _, _ = self.construct_message(allow_empty=True)
        if not conversation_payload:
            QMessageBox.warning(self, _("Empty Message"), _("Please enter a chat message."))
            return

        dialog = PromptPreviewDialog(
            controller=self.controller,
            conversation_payload=conversation_payload,
            parent=self
        )
        dialog.exec_()

    def mode_changed(self, index):
        mode = self.mode_selector.currentText()
        self.current_mode = mode

    def toggle_context_panel(self):
        if self.context_panel.isVisible():
            sizes = self.inner_splitter.sizes()
            if len(sizes) >= 2:
                self._left_panel_last_width = max(sizes[0], 0)
                self._context_panel_last_width = max(sizes[1], self.context_panel.minimumWidth())
                self.inner_splitter.setSizes([sizes[0] + sizes[1], 0])
            self.context_panel.setVisible(False)
            self.context_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book.svg"))
        else:
            self.context_panel.setVisible(True)
            desired_width = max(self._context_panel_last_width, self.context_panel.minimumWidth())
            left_width = max(self._left_panel_last_width, 0)
            if left_width <= 0:
                left_width = desired_width
            self.inner_splitter.setSizes([left_width, desired_width])
            self.context_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book-open.svg"))

    def generate_unique_chat_name(self):
        """Generate a unique chat name in the format 'Chat <number>'."""
        existing_numbers = []
        chat_pattern = re.compile(r'^Chat (\d+)$')
        
        # Extract numbers from existing chat names that match 'Chat <number>'
        for name in self.conversations.keys():
            match = chat_pattern.match(name)
            if match:
                existing_numbers.append(int(match.group(1)))
        
        # Find the next largest positive integer
        number = 1
        for n in existing_numbers:
            if n >= number:
                number = n + 1
        
        return f"Chat {number}"

    def new_conversation(self):
        """Create a new conversation with a unique name."""
        new_chat_name = self.generate_unique_chat_name()
        self.conversations[new_chat_name] = []
        self.conversation_list.addItem(new_chat_name)
        self.conversation_list.setCurrentRow(self.conversation_list.count() - 1)
        self.save_conversations()

    def get_scene_text(self, scene_name):
        for act in self.structure.get("acts", []):
            for chapter in act.get("chapters", []):
                for scene in chapter.get("scenes", []):
                    if scene.get("name", "").lower() == scene_name.lower():
                        hierarchy = [act.get("name"), chapter.get("name"), scene.get("name")]
                        content = load_latest_autosave(self.project_name, hierarchy, scene)
                        return content or f"[No content for scene {scene_name}]"
        return f"[No content for scene {scene_name}]"

    def on_send_or_stop(self):
        """Toggle between sending a message (start streaming) and stopping streaming."""
        if self.is_streaming:
            # Stop streaming and prompt to save/discard
            self.stop_llm()
        else:
            # Start streaming
            user_message = self.chat_input.toPlainText().strip()
            if not user_message:
                return
            self.is_streaming = True
            self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/x-octagon.svg"))
            self.send_message()

    def send_message(self):
        """Send a message to the LLM using streaming and update chat bubbles."""
        user_message = self.chat_input.toPlainText().strip()
        if not user_message:
            return

        self.pending_user_text = user_message

        user_entry = ChatMessage.from_legacy("user", user_message)
        self.conversation_history.append(user_entry)
        self.pending_user_message_id = user_entry.id
        self.chat_list.add_or_update_message(user_entry, select=True)
        self.conversations[self.current_conversation] = self.conversation_history
        self.save_conversations()
        QApplication.processEvents()

        try:
            conversation_payload, overrides_used, prompt_config, prompt_messages = self.construct_message()
            if not conversation_payload:
                raise ValueError("Conversation payload is empty")

            overrides_for_worker = deepcopy(overrides_used)
            user_entry.metadata["augmented_content"] = conversation_payload[-1]["content"]
            user_entry.metadata["overrides"] = deepcopy(overrides_used)
            if prompt_messages:
                user_entry.metadata["prompt_messages"] = deepcopy(prompt_messages)
                user_entry.metadata["prompt_text"] = "\n\n".join(
                    entry["content"]
                    for entry in prompt_messages
                    if entry.get("role", "system") == "system"
                )
            elif prompt_config:
                user_entry.metadata["prompt_text"] = prompt_config.get("text", "")
            else:
                user_entry.metadata.pop("prompt_text", None)
                user_entry.metadata.pop("prompt_messages", None)

            assistant_entry = ChatMessage.from_legacy("assistant", "")
            self.conversation_history.append(assistant_entry)
            self.streaming_message_id = assistant_entry.id
            self.chat_list.add_or_update_message(assistant_entry, select=True)

            self.streaming_mode = "send"
            self.previous_variant_index = None
            self.streaming_variant_id = assistant_entry.active_variant.id

            self.worker = LLMWorker("", overrides=overrides_for_worker, conversation_history=conversation_payload)
            self.worker.data_received.connect(self.append_streamed_response)
            self.worker.finished.connect(self.on_streaming_finished)
            self.worker.token_limit_exceeded.connect(self.handle_token_limit_error)
            self.worker.start()
        except Exception as e:
            logging.error(f"Failed to start streaming: {e}", exc_info=True)
            QMessageBox.warning(self, _("Error"), _("Failed to generate response: {}").format(str(e)))
            if self.streaming_message_id:
                self.remove_message(self.streaming_message_id)
            self.streaming_message_id = None
            self.pending_user_message_id = None
            self.pending_user_text = ""
            self.streaming_mode = None
            self.previous_variant_index = None
            self.streaming_variant_id = None
            self.is_streaming = False
            self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg"))
            self.cleanup_worker()

    def append_streamed_response(self, chunk):
        """Append a streamed chunk to the active assistant bubble."""
        if not chunk or not isinstance(chunk, str):
            return
        message = self.get_message_by_id(self.streaming_message_id)
        if not message:
            return
        message.set_content(message.content + chunk)
        self.chat_list.add_or_update_message(message)
        QApplication.processEvents()

    def on_streaming_finished(self):
        """Handle completion of streaming."""
        logging.debug(
            "Streaming finished, worker: %s, interrupt_flag: %s",
            id(self.worker) if self.worker else None,
            WWApiAggregator.interrupt_flag.is_set()
        )
        self.cleanup_worker()
        self.finalize_streaming_message(save=True)
        self.is_streaming = False
        self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg"))
        QApplication.processEvents()

    def handle_token_limit_error(self, error_msg):
        """Handle token limit errors during streaming."""
        QMessageBox.warning(self, _("Token Limit Exceeded"), error_msg)
        self.stop_llm()

    def stop_llm(self):
        """Stop the LLM streaming process and prompt to save/discard output."""
        try:
            if self.worker and self.worker.isRunning():
                logging.debug("Calling worker.stop()")
                self.worker.stop()
                logging.debug("Calling WWApiAggregator.interrupt()")
                WWApiAggregator.interrupt()
            logging.debug("Calling cleanup_worker")
            self.cleanup_worker()
        except Exception as e:
            logging.error(f"Error in stop_llm: {e}", exc_info=True)
            raise

        assistant_message = self.get_message_by_id(self.streaming_message_id)
        content = assistant_message.content.strip() if assistant_message else ""
        is_swipe = self.streaming_mode == "swipe"

        try:
            if content:
                reply = QMessageBox.question(
                    self,
                    _("Save Streamed Output"),
                    _("Streaming was interrupted. Would you like to save the output received so far?"),
                    QMessageBox.Save | QMessageBox.Discard
                )
                logging.debug("QMessageBox reply: %s", reply)
                if reply == QMessageBox.Save:
                    self.finalize_streaming_message(save=True)
                else:
                    if is_swipe:
                        self.finalize_streaming_message(save=False)
                    else:
                        self.finalize_streaming_message(save=False, discard_user=True, restore_input=True)
            else:
                if is_swipe:
                    self.finalize_streaming_message(save=False)
                else:
                    self.finalize_streaming_message(save=False, discard_user=True, restore_input=True)
        except Exception as e:
            logging.error(f"Error in stop_llm response handling: {e}", exc_info=True)
            raise

        self.is_streaming = False
        self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg"))

    def finalize_streaming_message(self, save=True, discard_user=False, restore_input=False):
        assistant_message = self.get_message_by_id(self.streaming_message_id)
        user_message = self.get_message_by_id(self.pending_user_message_id)
        is_swipe = self.streaming_mode == "swipe"

        should_save = bool(save and assistant_message and assistant_message.content.strip())

        if assistant_message:
            if is_swipe:
                if should_save:
                    self.chat_list.add_or_update_message(assistant_message)
                else:
                    if self.streaming_variant_id:
                        assistant_message.remove_variant(self.streaming_variant_id)
                    if self.previous_variant_index is not None and assistant_message.variants:
                        assistant_message.active_index = min(self.previous_variant_index, len(assistant_message.variants) - 1)
                    self.chat_list.add_or_update_message(assistant_message)
            else:
                if should_save:
                    self.chat_list.add_or_update_message(assistant_message)
                else:
                    self.remove_message(self.streaming_message_id)

        if discard_user and user_message and not is_swipe:
            self.remove_message(self.pending_user_message_id)

        if restore_input and self.pending_user_text:
            self.chat_input.setPlainText(self.pending_user_text)
            cursor = self.chat_input.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.chat_input.setTextCursor(cursor)
        elif not restore_input and not is_swipe:
            self.chat_input.clear()

        self.conversations[self.current_conversation] = self.conversation_history
        self.save_conversations()

        self.pending_user_message_id = None
        self.streaming_message_id = None
        self.pending_user_text = ""
        self.streaming_mode = None
        self.previous_variant_index = None
        self.streaming_variant_id = None

    def get_message_by_id(self, message_id):
        if not message_id:
            return None
        for message in self.conversation_history:
            if message.id == message_id:
                return message
        return None

    def remove_message(self, message_id):
        if not message_id:
            return
        message = self.get_message_by_id(message_id)
        if not message:
            return
        try:
            self.conversation_history.remove(message)
        except ValueError:
            return
        self.chat_list.remove_message(message_id)

    def handle_swipe_request(self, message_id):
        if self.is_streaming:
            QMessageBox.information(
                self,
                _("Streaming in Progress"),
                _("Please wait for the current response to finish before swiping."),
            )
            return

        assistant_message = self.get_message_by_id(message_id)
        if not assistant_message or assistant_message.role != "assistant":
            return

        try:
            message_index = self.conversation_history.index(assistant_message)
        except ValueError:
            return

        if message_index == 0:
            QMessageBox.information(
                self,
                _("Swipe Unavailable"),
                _("There's no earlier user message to regenerate from."),
            )
            return

        history_up_to = self.conversation_history[:message_index]
        user_message = next((msg for msg in reversed(history_up_to) if msg.role == "user"), None)
        if not user_message:
            QMessageBox.information(
                self,
                _("Swipe Unavailable"),
                _("Swipe is only supported for assistant replies following a user message."),
            )
            return

        prompt_seed = user_message.metadata.get("prompt_messages") or user_message.metadata.get("prompt_text")
        payload = self.build_payload_for_history(history_up_to, prompt_seed)
        if not payload or payload[-1]["role"] != "user":
            payload.append({
                "role": "user",
                "content": user_message.metadata.get("augmented_content", user_message.content)
            })

        overrides_source = user_message.metadata.get("overrides")
        if overrides_source is None:
            overrides_source = self.prompt_panel.get_overrides() or {}
        overrides_for_worker = deepcopy(overrides_source)

        try:
            self.pending_user_message_id = user_message.id
            self.streaming_message_id = assistant_message.id
            self.pending_user_text = ""
            self.streaming_mode = "swipe"
            self.previous_variant_index = assistant_message.active_index
            new_variant = assistant_message.add_variant("", set_active=True)
            self.streaming_variant_id = new_variant.id
            self.chat_list.add_or_update_message(assistant_message, select=True)

            self.worker = LLMWorker("", overrides=overrides_for_worker, conversation_history=payload)
            self.worker.data_received.connect(self.append_streamed_response)
            self.worker.finished.connect(self.on_streaming_finished)
            self.worker.token_limit_exceeded.connect(self.handle_token_limit_error)

            self.is_streaming = True
            self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/x-octagon.svg"))
            self.worker.start()
        except Exception as e:
            logging.error(f"Failed to start swipe regeneration: {e}", exc_info=True)
            QMessageBox.warning(self, _("Error"), _("Failed to regenerate response: {}").format(str(e)))
            if self.streaming_variant_id:
                assistant_message.remove_variant(self.streaming_variant_id)
                if self.previous_variant_index is not None:
                    assistant_message.active_index = min(self.previous_variant_index, len(assistant_message.variants) - 1)
                self.chat_list.add_or_update_message(assistant_message)
            self.pending_user_message_id = None
            self.streaming_message_id = None
            self.streaming_mode = None
            self.previous_variant_index = None
            self.streaming_variant_id = None
            self.is_streaming = False
            self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg"))

    def handle_prev_variant(self, message_id):
        if self.is_streaming:
            return
        message = self.get_message_by_id(message_id)
        if not message or message.role != "assistant":
            return
        if message.active_index <= 0:
            return
        message.active_index -= 1
        self.chat_list.add_or_update_message(message, select=True)
        self.conversations[self.current_conversation] = self.conversation_history
        self.save_conversations()

    def handle_next_variant(self, message_id):
        if self.is_streaming:
            return
        message = self.get_message_by_id(message_id)
        if not message or message.role != "assistant":
            return
        if message.active_index >= len(message.variants) - 1:
            return
        message.active_index += 1
        self.chat_list.add_or_update_message(message, select=True)
        self.conversations[self.current_conversation] = self.conversation_history
        self.save_conversations()

    def handle_branch_request(self, message_id):
        if self.is_streaming:
            QMessageBox.information(
                self,
                _("Streaming in Progress"),
                _("Please wait for the current response to finish before branching."),
            )
            return

        message = self.get_message_by_id(message_id)
        if not message:
            return

        branch_history = clone_history_until(self.conversation_history, message_id)
        new_conversation_name = self.generate_unique_chat_name()
        self.conversations[new_conversation_name] = branch_history

        self.conversation_list.addItem(new_conversation_name)
        self.conversation_list.setCurrentRow(self.conversation_list.count() - 1)
        self.save_conversations()

    def cleanup_worker(self):
        """Clean up the LLMWorker thread and reset LLM provider state."""
        logging.debug(f"Starting cleanup_worker, worker: {id(self.worker) if self.worker else None}")
        try:
            if self.worker:
                worker_id = id(self.worker)
                if self.worker.isRunning():
                    logging.debug(f"Stopping worker {worker_id}")
                    self.worker.stop()
                    self.worker.wait(5000)  # Wait up to 5 seconds for the thread to stop
                    if self.worker.isRunning():
                        logging.warning(f"Worker {worker_id} did not stop in time; will not terminate to avoid potential crash")
                        #skip termination
                try:
                    logging.debug(f"Disconnecting signals for worker {worker_id}")
                    self.worker.data_received.disconnect()
                    self.worker.finished.disconnect()
                    self.worker.token_limit_exceeded.disconnect()
                except TypeError as e:
                    logging.debug(f"Signal disconnection error for worker {worker_id}: {e}")
                logging.debug(f"Scheduling worker {worker_id} for deletion")
                self.worker.deleteLater()  # Schedule deletion
                # Reset the LLM instance in the provider
                provider_name = self.prompt_panel.get_overrides().get("provider") or WWSettingsManager.get_active_llm_name()
                provider = WWApiAggregator.aggregator.get_provider(provider_name)
                logging.debug(f"Worker {worker_id} cleaned up")
                self.worker = None  # Clear reference
        except Exception as e:
            logging.error(f"Error cleaning up LLMWorker: {e}", exc_info=True)
            QMessageBox.critical(self, _("Thread Error"), _("An error occurred while stopping the LLM thread: {}").format(str(e)))

    def get_item_hierarchy(self, item):
        hierarchy = []
        while item:
            hierarchy.insert(0, item.text(0))
            item = item.parent()
        return hierarchy

    def show_conversation_context_menu(self, pos: QPoint):
        """Show context menu for conversation list items."""
        item = self.conversation_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu()
        rename_action = menu.addAction(_("Rename"))
        delete_action = menu.addAction(_("Delete"))
        action = menu.exec_(self.conversation_list.mapToGlobal(pos))
        if action == rename_action:
            self.rename_conversation(item)
        elif action == delete_action:
            self.delete_conversation(item)

    def rename_conversation(self, item: QListWidgetItem):
        """Rename the selected conversation, ensuring no overwrite."""
        current_name = item.text()
        assert current_name in self.conversations, f"Conversation {current_name} not found in self.conversations"

        while True:
            new_name, ok = QInputDialog.getText(
                self, _("Rename Conversation"), 
                _("Enter new conversation name:"), 
                text=current_name
            )
            if not ok:
                logging.info(f"User cancelled renaming conversation {current_name}")
                return  # User cancelled, no changes made

            new_name = new_name.strip()
            if not new_name:
                QMessageBox.warning(
                    self, _("Invalid Name"), 
                    _("The conversation name cannot be empty. Please try again.")
                )
                continue

            if new_name == current_name:
                logging.info(f"User kept same name {current_name} for conversation")
                return  # No change needed

            if new_name in self.conversations:
                QMessageBox.warning(
                    self, _("Name Conflict"), 
                    _("A conversation named '{}' already exists. Please choose a different name.").format(new_name)
                )
                continue

            # Backup conversation data
            backup_data = self.conversations[current_name].copy()
            logging.info(f"Renaming conversation from {current_name} to {new_name}")

            try:
                # Perform rename
                self.conversations[new_name] = self.conversations.pop(current_name)
                item.setText(new_name)
                if self.current_conversation == current_name:
                    self.current_conversation = new_name
                self.conversation_list.setCurrentItem(item)  # Ensure item remains selected
                self.save_conversations()

                # Verify state consistency
                assert new_name in self.conversations, f"Failed to add {new_name} to self.conversations"
                assert current_name not in self.conversations, f"{current_name} still in self.conversations"
                assert item.text() == new_name, f"List item text not updated to {new_name}"
                logging.info(f"Successfully renamed conversation from {current_name} to {new_name}")
                break

            except Exception as e:
                # Restore backup on error
                self.conversations[current_name] = backup_data
                if new_name in self.conversations:
                    del self.conversations[new_name]
                logging.error(f"Error renaming conversation {current_name} to {new_name}: {e}", exc_info=True)
                QMessageBox.critical(
                    self, _("Rename Error"), 
                    _("An error occurred while renaming the conversation: {}. The operation was cancelled to prevent data loss.").format(str(e))
                )
                return

    def delete_conversation(self, item: QListWidgetItem):
        """Delete the selected conversation."""
        conversation_name = item.text()
        reply = QMessageBox.question(
            self, _("Delete Conversation"), 
            _("Are you sure you want to delete '{}'?").format(conversation_name),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            row = self.conversation_list.row(item)
            self.conversation_list.takeItem(row)
            if conversation_name in self.conversations:
                del self.conversations[conversation_name]
            # Check if the list is empty
            if self.conversation_list.count() == 0:
                # Create a new default conversation
                self.current_conversation = "Chat 1"
                self.conversations[self.current_conversation] = []
                self.conversation_history = self.conversations[self.current_conversation]
                self.conversation_list.addItem(self.current_conversation)
                self.conversation_list.setCurrentRow(0)
                self.chat_list.clear_messages()
            # No need to manually load a conversation; itemSelectionChanged will handle it
            self.save_conversations()

    def on_conversation_selection_changed(self):
        """Sync the UI with the currently selected conversation."""
        selected_items = self.conversation_list.selectedItems()
        if selected_items:
            selected_name = selected_items[0].text()
            self.current_conversation = selected_name
            self.conversation_history = self.conversations.get(selected_name, [])
            if self.conversation_history is None:
                self.conversation_history = []
                self.conversations[selected_name] = self.conversation_history
            self.chat_list.populate(self.conversation_history)
            self.pending_user_message_id = None
            self.streaming_message_id = None
            self.pending_user_text = ""
        else:
            # No conversation selected (e.g., list is empty)
            self.current_conversation = None
            self.conversation_history = []
            self.chat_list.clear_messages()
            self.pending_user_message_id = None
            self.streaming_message_id = None
            self.pending_user_text = ""
        if not self._is_initial_load:
            self.save_conversations()

    def load_conversations(self):
        """Load conversations from file and initialize the UI."""
        self._is_initial_load = True
        last_viewed_chat = "Chat 1"
        conversations_path = "conversations.json"
        self.conversations = {}

        if os.path.exists(conversations_path):
            try:
                with open(conversations_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict) and "conversations" in data:
                    raw_conversations = data.get("conversations", {})
                    last_viewed_chat = data.get("last_viewed_chat", last_viewed_chat)
                elif isinstance(data, dict):
                    raw_conversations = data
                else:
                    raw_conversations = {}

                for conv_name, messages in raw_conversations.items():
                    if isinstance(messages, list):
                        self.conversations[conv_name] = deserialize_messages(messages)

                if not self.conversations:
                    self.conversations = {"Chat 1": []}
            except Exception as e:
                logging.error(f"Error loading conversations: {e}", exc_info=True)
                self.conversations = {"Chat 1": []}
        else:
            logging.info("No conversations.json found, initializing default")
            self.conversations = {"Chat 1": []}

        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        for conv_name in self.conversations:
            self.conversation_list.addItem(conv_name)

        if last_viewed_chat not in self.conversations:
            last_viewed_chat = next(iter(self.conversations.keys()))

        for i in range(self.conversation_list.count()):
            if self.conversation_list.item(i).text() == last_viewed_chat:
                self.conversation_list.setCurrentRow(i)
                break

        self.conversation_list.blockSignals(False)

        self.current_conversation = last_viewed_chat
        self.conversation_history = self.conversations.get(self.current_conversation, [])
        if self.conversation_history is None:
            self.conversation_history = []
            self.conversations[self.current_conversation] = self.conversation_history

        self.chat_list.populate(self.conversation_history)
        self._is_initial_load = False

    def save_conversations(self):
        """Save conversations to file."""
        try:
            # Verify state before saving
            for name in self.conversations:
                assert isinstance(self.conversations[name], list), f"Conversation {name} has invalid data"
            payload = {
                "conversations": {
                    name: serialize_messages(messages)
                    for name, messages in self.conversations.items()
                },
                "last_viewed_chat": self.current_conversation
            }
            with open("conversations.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4)
            logging.debug("Conversations saved successfully")
        except Exception as e:
            logging.error(f"Error saving conversations: {e}", exc_info=True)
            QMessageBox.warning(
                self, _("Save Error"), 
                _("Failed to save conversations: {}. Your data is safe in memory, but try saving again later.").format(str(e))
            )

    def toggle_recording(self):
        if not self.record_button.isChecked():
            self.recorder.stop_recording()
            self.recording_timer.stop()
            self.pause_button.setEnabled(False)
            self.record_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/mic.svg"))
            self.time_label.setText("00:00")
        else:
            self.recording_file = tempfile.mktemp(suffix='.wav')
            self.recorder = AudioRecorder()
            self.recorder.setup_recording(self.recording_file)
            self.recorder.finished.connect(self.on_recording_finished)
            self.recorder.start()
            
            self.start_time = datetime.datetime.now()
            self.pause_start = None
            self.recording_timer.start(1000)
            self.pause_button.setEnabled(True)
            self.record_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/stop-circle.svg"))

    def toggle_pause(self):
        if self.recorder.is_paused:
            self.recorder.resume()
            self.pause_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/pause.svg"))
            if self.pause_start:
                pause_duration = datetime.datetime.now() - self.pause_start
                self.start_time += pause_duration
                self.pause_start = None
        else:
            self.recorder.pause()
            self.pause_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/play.svg"))
            self.pause_start = datetime.datetime.now()

    def update_recording_time(self):
        if self.start_time and not self.recorder.is_paused:
            delta = datetime.datetime.now() - self.start_time
            if self.pause_start:
                delta -= datetime.datetime.now() - self.pause_start
            self.time_label.setText(str(delta).split('.')[0])

    def on_recording_finished(self, file_path):
        QApplication.setOverrideCursor(self.waiting_cursor)
        language = None if self.language_combo.currentText() == "Auto" else self.language_combo.currentText()
        self.transcription_worker = TranscriptionWorker(
            file_path, 
            self.model_combo.currentText(),
            language
        )
        self.transcription_worker.finished.connect(self.handle_transcription)
        self.transcription_worker.start()

    def handle_transcription(self, text):
        QApplication.restoreOverrideCursor()
        if not text.startswith("Error"):
            current_text = self.chat_input.toPlainText()
            if current_text:
                self.chat_input.setPlainText(current_text + " " + text)
            else:
                self.chat_input.setPlainText(text)
        else:
            QMessageBox.warning(self, _("Transcription Error"), text)

class AudioRecorder(QThread):
    finished = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.is_recording = False
        self.is_paused = False
        self.output_file = ""
        self.start_time = None

    def setup_recording(self, output_file):
        self.output_file = output_file
        self.is_recording = True
        self.is_paused = False
        self.start_time = datetime.datetime.now()

    def run(self):
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        CHUNK = 1024
        
        audio = pyaudio.PyAudio()
        stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        frames = []
        
        while self.is_recording:
            data = stream.read(CHUNK)
            if not self.is_paused:
                frames.append(data)
            self.msleep(10)
            
        stream.stop_stream()
        stream.close()
        audio.terminate()
        
        if frames:
            wf = wave.open(self.output_file, 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(audio.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
            wf.close()
            self.finished.emit(self.output_file)

    def stop_recording(self):
        self.is_recording = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

class TranscriptionWorker(QThread):
    finished = pyqtSignal(str)
    
    def __init__(self, file_path, model_name="tiny", language=None):
        super().__init__()
        self.file_path = file_path
        self.model_name = model_name
        self.language = language

    def run(self):
        try:
            model = whisper.load_model(self.model_name)
            result = model.transcribe(self.file_path, language=self.language)
            self.finished.emit(result["text"])
        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    window = WorkshopWindow()
    window.show()
    sys.exit(app.exec_())

