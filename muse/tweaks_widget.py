from PyQt5.QtWidgets import QWidget
from PyQt5 import uic

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s

class TweaksWidget(QWidget):
    """Widget for additional prompt tweaks (instructions, word count, etc.)."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi("ui_files/dialogs/tweaks_widget.ui", self)
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize UI components."""
        # Set default value for output word count
        self.output_word_count_combo.setCurrentText("200")
    
    def get_tweak_values(self):
        """
        Collect current values from all tweak widgets.
        
        Returns:
            dict: Dictionary with tweak variable names and their values
        """
        return {
            'additionalInstructions': self.additional_instructions_edit.toPlainText().strip(),
            'outputWordCount': self.output_word_count_combo.currentText().strip()
        }
    
    def set_tweak_values(self, values):
        """
        Set tweak widget values from a dictionary.
        
        Args:
            values (dict): Dictionary with tweak variable names and values
        """
        if 'additionalInstructions' in values:
            self.additional_instructions_edit.setPlainText(values['additionalInstructions'])
        
        if 'outputWordCount' in values:
            self.output_word_count_combo.setCurrentText(str(values['outputWordCount']))
    
    def clear_tweaks(self):
        """Clear all tweak inputs."""
        self.additional_instructions_edit.clear()
        self.output_word_count_combo.setCurrentText("200")
