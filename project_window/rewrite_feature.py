# rewrite_feature.py
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QComboBox,
    QPushButton, QMessageBox
)
from muse.prompt_utils import load_prompts
from settings.llm_worker import LLMWorker
from muse.prompt_preview_dialog import PromptPreviewDialog

# Translation function fallback
import builtins
if not hasattr(builtins, '_'):
    def _(text):
        return text
    builtins._ = _

class RewriteDialog(QDialog):
    """
    A dialog for rewriting a selected passage.
    
    Features:
      - Displays the original (read-only) text.
      - Provides a dropdown list of available rewrite prompts.
      - A "Preview Prompt" button shows the preview prompt dialog with the selected prompt.
      - Displays the rewritten text for comparison.
      - "Generate" allows re-generation with the same prompt.
      - "Apply" confirms the change (the dialog is accepted) so the caller can replace the selected text.
    """
    def __init__(self, project_name, original_text, parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.original_text = original_text
        self.rewritten_text = ""
        self.worker = None
        self.controller = parent  # Store parent reference as controller
        self.setWindowTitle(_("Rewrite Selected Text"))
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Display original text.
        orig_label = QLabel(_("Original Text:"))
        layout.addWidget(orig_label)
        self.orig_edit = QTextEdit()
        self.orig_edit.setPlainText(self.original_text)
        layout.addWidget(self.orig_edit)
        
        # Dropdown for selecting a rewrite prompt.
        prompt_layout = QHBoxLayout()
        prompt_label = QLabel(_("Select Rewrite Prompt:"))
        prompt_layout.addWidget(prompt_label)
        self.prompt_combo = QComboBox()
        self.prompts = load_prompts("Rewrite")
        if not self.prompts:
            QMessageBox.warning(self, _("Rewrite"), _("No rewrite prompts found."))
        else:
            for p in self.prompts:
                self.prompt_combo.addItem(p.get("name", "Unnamed"))
        prompt_layout.addWidget(self.prompt_combo)
        layout.addLayout(prompt_layout)
        
        # Button to preview the prompt.
        self.preview_button = QPushButton(_("Preview Prompt"))
        self.preview_button.clicked.connect(self.show_preview_prompt)
        layout.addWidget(self.preview_button)
        
        # Display rewritten text.
        new_label = QLabel(_("Rewritten Text:"))
        layout.addWidget(new_label)
        self.new_edit = QTextEdit()
        self.new_edit.setReadOnly(True)
        layout.addWidget(self.new_edit)
        
        # Control buttons.
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton(_("Apply"))
        self.apply_button.clicked.connect(self.apply_rewrite)
        button_layout.addWidget(self.apply_button)
        self.retry_button = QPushButton(_("Generate"))
        self.retry_button.clicked.connect(self.retry_rewrite)
        button_layout.addWidget(self.retry_button)
        self.cancel_button = QPushButton(_("Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

    def update_text(self, text):
        self.new_edit.insertPlainText(text)

    def on_finished(self):
        pass
    
    def show_preview_prompt(self):
        """Show the preview prompt dialog with the selected rewrite prompt."""
        if not self.prompts:
            QMessageBox.warning(self, _("Rewrite"), _("No rewrite prompts available."))
            return
        
        index = self.prompt_combo.currentIndex()
        prompt_config = self.prompts[index]
        
        if not prompt_config:
            QMessageBox.warning(self, _("Rewrite"), _("Invalid prompt configuration."))
            return
        
        # Prepare variables for prompt assembly
        additional_vars = {
            'selectedText': self.orig_edit.toPlainText()
        }
        
        # Show the preview dialog
        try:
            dialog = PromptPreviewDialog(
                controller=self.controller,
                conversation_payload=None,
                prompt_config=prompt_config,
                user_input=self.orig_edit.toPlainText(),
                additional_vars=additional_vars,
                current_scene_text=None,
                extra_context=None,
                parent=self
            )
            
            # Connect signal to handle sending the prompt
            dialog.promptConfigReady.connect(self.on_prompt_ready)
            
            dialog.exec_()
        except Exception as e:
            QMessageBox.warning(self, _("Rewrite"), _("Error opening preview dialog: {}").format(str(e)))
    
    def on_prompt_ready(self, modified_config):
        """Handle the prompt being sent from the preview dialog."""
        # This will be called when the user clicks "Send" in the preview dialog
        # The modified_config contains any tweaks made in the dialog
        self.generate_rewrite_with_config(modified_config)
    
    def generate_rewrite_with_config(self, prompt_config):
        """Generate rewrite using the provided prompt configuration."""
        if not prompt_config:
            return
        
        # Handle chat completion style prompts (messages array)
        messages = prompt_config.get("messages", [])
        if messages:
            # Convert messages array to a formatted prompt text
            prompt_parts = []
            for message in messages:
                role = message.get("role", "")
                content = message.get("content", "")
                if role and content:
                    prompt_parts.append(f"{role}: {content}")
            
            if not prompt_parts:
                QMessageBox.warning(self, _("Rewrite"), _("Selected prompt has no valid messages."))
                return
            
            prompt_text = "\n\n".join(prompt_parts)
        else:
            # Fallback to legacy text field for backwards compatibility
            prompt_text = prompt_config.get("text", "")
            if not prompt_text:
                QMessageBox.warning(self, _("Rewrite"), _("Selected prompt has no text or messages."))
                return
        
        self.new_edit.clear()  # Clear previous rewritten text.

        # Construct final prompt with the original passage appended
        final_prompt = f"{prompt_text}\n\nOriginal Passage:\n{self.orig_edit.toPlainText()}"
        
        # Build the overrides dictionary
        overrides = {
            "provider": prompt_config.get("provider", "Local"),
            "model": prompt_config.get("model", "Local Model"),
            "max_tokens": prompt_config.get("max_tokens", 2000),
            "temperature": prompt_config.get("temperature", 1.0)
        }
        
        try:
            self.worker = LLMWorker(final_prompt, overrides)
            self.worker.data_received.connect(self.update_text)
            self.worker.finished.connect(self.on_finished)
            self.worker.finished.connect(self.cleanup_worker)  # Schedule thread deletion
            self.worker.start()
        except Exception as e:
            QMessageBox.warning(self, _("Rewrite"), _("Error sending prompt to LLM: {}").format(str(e)))
            return

    
    def retry_rewrite(self):
        # Re-generate using the same selected prompt.
        if not self.prompts:
            return
        index = self.prompt_combo.currentIndex()
        prompt_config = self.prompts[index]
        self.generate_rewrite_with_config(prompt_config)
    
    def apply_rewrite(self):
        self.rewritten_text = self.new_edit.toPlainText()
        if not self.rewritten_text:
            QMessageBox.warning(self, _("Rewrite"), _("No rewritten text to apply."))
            return
        self.accept()  # The caller can then retrieve self.rewritten_text.

    def cleanup_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.wait()  # Wait for the thread to fully stop
        if self.worker:
            try:
                self.worker.data_received.disconnect()
                self.worker.finished.disconnect()
            except TypeError:
                pass  # Signals may already be disconnected
            self.worker.deleteLater()  # Schedule deletion
            self.worker = None  # Clear reference

