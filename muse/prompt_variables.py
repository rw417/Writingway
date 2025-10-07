# prompt_variables.py
"""
Centralized prompt variable system for Writingway.
Provides a clean way to define and collect variables that can be used in prompt templates.
"""

from typing import Dict, Any, Callable, Optional
from PyQt5.QtWidgets import QTextEdit
from PyQt5.QtGui import QTextCursor

class PromptVariableManager:
    """Manages prompt variables and their collection from UI components."""
    
    def __init__(self):
        self._collectors = {}
        self._register_default_collectors()
    
    def register_collector(self, variable_name: str, collector_func: Callable[[], str]):
        """Register a function to collect a variable's value."""
        self._collectors[variable_name] = collector_func
    
    def unregister_collector(self, variable_name: str):
        """Remove a variable collector."""
        self._collectors.pop(variable_name, None)
    
    def get_all_variables(self) -> Dict[str, str]:
        """Collect all registered variables and their current values."""
        variables = {}
        for name, collector in self._collectors.items():
            try:
                value = collector()
                variables[name] = str(value) if value is not None else ""
            except Exception as e:
                print(f"Error collecting variable '{name}': {e}")
                variables[name] = ""
        return variables
    
    def get_variable(self, name: str) -> str:
        """Get the current value of a specific variable."""
        collector = self._collectors.get(name)
        if collector:
            try:
                value = collector()
                return str(value) if value is not None else ""
            except Exception as e:
                print(f"Error collecting variable '{name}': {e}")
        return ""
    
    def _register_default_collectors(self):
        """Register default variable collectors that don't depend on UI components."""
        # These will be overridden when UI components are set
        self._collectors.update({
            'pov': lambda: "",
            'pov_character': lambda: "", 
            'tense': lambda: "",
            'story_so_far': lambda: "",
            'sceneBeat': lambda: "",
            'context': lambda: "",
            'user_input': lambda: "",
            'selectedText': lambda: "",
            'additionalInstructions': lambda: "",
            'outputWordCount': lambda: "200",
        })

class ProjectVariableManager(PromptVariableManager):
    """Project-specific variable manager that integrates with UI components."""
    
    def __init__(self, project_window=None):
        super().__init__()
        self.project_window = project_window
        if project_window:
            self.setup_ui_collectors(project_window)
    
    def setup_ui_collectors(self, project_window):
        """Setup collectors that depend on UI components."""
        # Get references to UI components
        right_stack = getattr(project_window, 'right_stack', None)
        scene_editor = getattr(project_window, 'scene_editor', None)
        project_tree = getattr(project_window, 'project_tree', None)
        
        if right_stack:
            # POV settings
            self.register_collector('pov', 
                lambda: getattr(right_stack.pov_combo, 'currentText', lambda: "")())
            self.register_collector('pov_character', 
                lambda: getattr(right_stack.pov_character_combo, 'currentText', lambda: "")())
            self.register_collector('tense', 
                lambda: getattr(right_stack.tense_combo, 'currentText', lambda: "")())
            
            # Action beats
            self.register_collector('sceneBeat', 
                lambda: getattr(right_stack.prompt_input, 'toPlainText', lambda: "")())
            
            # Context from context panel
            self.register_collector('context', 
                lambda: getattr(right_stack.context_panel, 'get_selected_context_text', lambda: "")() if hasattr(right_stack, 'context_panel') else "")
        
        if scene_editor and project_tree:
            # Current scene text (story so far)
            def get_story_so_far():
                current_item = project_tree.tree.currentItem()
                if current_item and project_tree.get_item_level(current_item) >= 2:
                    return scene_editor.editor.toPlainText().strip()
                return ""
            self.register_collector('story_so_far', get_story_so_far)
            
            # Selected text in editor
            def get_selected_text():
                editor = scene_editor.editor
                if hasattr(editor, 'textCursor'):
                    cursor = editor.textCursor()
                    if cursor.hasSelection():
                        return cursor.selectedText()
                return ""
            self.register_collector('selectedText', get_selected_text)
        
        # User input (will be set dynamically when sending prompts)
        self._user_input_value = ""
        self.register_collector('user_input', lambda: self._user_input_value)
    
    def set_user_input(self, user_input: str):
        """Set the user input value for prompt assembly."""
        self._user_input_value = user_input or ""
    
    def add_custom_variable(self, name: str, value_func: Callable[[], str]):
        """Add a custom variable with a collector function."""
        self.register_collector(name, value_func)
    
    def add_static_variable(self, name: str, value: str):
        """Add a static variable with a fixed value."""
        self.register_collector(name, lambda: str(value))

# Global instance - will be initialized by ProjectWindow
variable_manager: Optional[ProjectVariableManager] = None

def initialize_variable_manager(project_window):
    """Initialize the global variable manager with UI components."""
    global variable_manager
    variable_manager = ProjectVariableManager(project_window)
    return variable_manager

def get_variable_manager() -> Optional[ProjectVariableManager]:
    """Get the current variable manager instance."""
    return variable_manager

def get_prompt_variables() -> Dict[str, str]:
    """Get all current prompt variables."""
    if variable_manager:
        return variable_manager.get_all_variables()
    return {}

def set_user_input(user_input: str):
    """Set the user input for prompt assembly."""
    if variable_manager:
        variable_manager.set_user_input(user_input)