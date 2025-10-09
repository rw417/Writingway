from PyQt5.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5 import uic
from project_window.tweaks_widget import TweaksWidget
from muse.preview_widget import PreviewWidget

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s

class PromptDialogTabbed(QDialog):
    """Tabbed dialog for prompt tweaks and preview."""
    
    # Signal to send modified prompt config to main window
    promptConfigReady = pyqtSignal(dict)
    
    def __init__(self, controller, conversation_payload=None, prompt_config=None, user_input=None,
                 additional_vars=None, current_scene_text=None, extra_context=None, parent=None):
        super().__init__(parent)
        uic.loadUi("ui_files/dialogs/prompt_dialog_tabbed.ui", self)
        
        self.controller = controller
        self.conversation_payload = conversation_payload
        self.prompt_config = prompt_config
        self.user_input = user_input
        self.additional_vars = additional_vars or {}
        self.current_scene_text = current_scene_text
        self.extra_context = extra_context
        
        self.setup_ui()
        self.read_settings()
        self.setMinimumSize(self.size())
    
    def setup_ui(self):
        """Initialize UI components."""
        # Create tweaks widget
        self.tweaks_widget = TweaksWidget(self)
        tweaks_layout = self.tweaks_tab.findChild(QVBoxLayout, "tweaks_layout")
        if tweaks_layout:
            # Remove placeholder and add real widget
            placeholder = self.tweaks_tab.findChild(type(None), "tweaks_container")
            if placeholder:
                tweaks_layout.removeWidget(placeholder)
                placeholder.deleteLater()
            tweaks_layout.addWidget(self.tweaks_widget)
        
        # Create preview widget
        self.preview_widget = PreviewWidget(self.controller, self)
        preview_layout = self.preview_tab.findChild(QVBoxLayout, "preview_layout")
        if preview_layout:
            # Remove placeholder and add real widget
            placeholder = self.preview_tab.findChild(type(None), "preview_container")
            if placeholder:
                preview_layout.removeWidget(placeholder)
                placeholder.deleteLater()
            preview_layout.addWidget(self.preview_widget)
        
        # Set initial prompt data in preview widget
        self.preview_widget.set_prompt_data(
            self.conversation_payload,
            self.prompt_config,
            self.user_input,
            self.additional_vars,
            self.current_scene_text,
            self.extra_context
        )
        
        # Initial preview refresh
        self.preview_widget.refresh_preview()
        
        # Connect signals
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.preview_widget.sendPromptRequested.connect(self.on_send_prompt)
        self.preview_widget.returnRequested.connect(self.accept)
    
    def on_tab_changed(self, index):
        """Handle tab change - refresh preview when switching to Preview tab."""
        # Check if we're switching to the Preview tab (index 1)
        if index == 1:
            # Get current tweak values
            tweak_values = self.tweaks_widget.get_tweak_values()
            
            # Refresh preview with tweak values
            self.preview_widget.refresh_preview(tweak_overrides=tweak_values)
    
    def on_send_prompt(self, modified_config):
        """Handle send prompt request from preview widget."""
        # Emit signal to parent
        self.promptConfigReady.emit(modified_config)
        # Close dialog
        self.accept()
    
    def read_settings(self):
        """Load saved settings."""
        settings = QSettings("MyCompany", "WritingwayProject")
        geometry = settings.value("prompt_dialog_tabbed/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Restore font size in preview widget if saved
        font_size = settings.value("prompt_dialog_tabbed/fontSize", 12, type=int)
        if hasattr(self.preview_widget, 'font_size'):
            self.preview_widget.font_size = font_size
            self.preview_widget.update_font_size()
    
    def write_settings(self):
        """Save current settings."""
        settings = QSettings("MyCompany", "WritingwayProject")
        settings.setValue("prompt_dialog_tabbed/geometry", self.saveGeometry())
        
        # Save font size from preview widget
        if hasattr(self.preview_widget, 'font_size'):
            settings.setValue("prompt_dialog_tabbed/fontSize", self.preview_widget.font_size)
    
    def closeEvent(self, event):
        """Handle dialog close event."""
        self.write_settings()
        event.accept()
