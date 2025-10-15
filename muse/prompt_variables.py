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
        # collectors that accept parameters: name -> callable(*args, **kwargs)
        self._param_collectors = {}
        self._register_default_collectors()
    
    def register_collector(self, variable_name: str, collector_func: Callable[[], str]):
        """Register a function to collect a variable's value."""
        self._collectors[variable_name] = collector_func
    
    def unregister_collector(self, variable_name: str):
        """Remove a variable collector."""
        self._collectors.pop(variable_name, None)
    
    def get_all_variables(self) -> Dict[str, str]:
        """Collect all registered variables and their current values."""
        variables: Dict[str, Any] = {}
        for name, collector in self._collectors.items():
            try:
                value = collector()
                value_str = str(value) if value is not None else ""
            except Exception as e:
                print(f"Error collecting variable '{name}': {e}")
                value_str = ""

            # If collector name contains dot notation (e.g., 'scene.fullText'),
            # build nested dictionaries so Jinja2 can access `scene.fullText`.
            if '.' in name:
                parts = name.split('.')
                top = parts[0]
                rest = parts[1:]
                node = variables.setdefault(top, {})
                # If an earlier non-dict value existed for this top-level key, overwrite it
                if not isinstance(node, dict):
                    node = {}
                    variables[top] = node
                cur = node
                for part in rest[:-1]:
                    cur = cur.setdefault(part, {})
                cur[rest[-1]] = value_str
            else:
                variables[name] = value_str

        return variables

    def register_param_collector(self, variable_name: str, collector_func: Callable[..., str]):
        """Register a function that accepts parameters for a variable like wordsBefore(200, True)."""
        self._param_collectors[variable_name] = collector_func

    def unregister_param_collector(self, variable_name: str):
        self._param_collectors.pop(variable_name, None)

    def evaluate_param_variable(self, variable_name: str, args: list):
        """Evaluate a parameterized variable by name with a list of positional args.

        Returns string result or raises if not found.
        """
        func = self._param_collectors.get(variable_name)
        if not func:
            raise KeyError(variable_name)
        try:
            # Call the collector with positional args
            return str(func(*args))
        except Exception as e:
            print(f"Error evaluating parameterized variable '{variable_name}': {e}")
            return ""
    
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
        # Expose this instance as the global variable manager for convenience
        global variable_manager
        variable_manager = self
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

            # Scene full text and scene summary collectors
            def get_scene_full_text():
                try:
                    # Use project_tree current item to ensure a scene is selected
                    current_item = getattr(project_window, 'project_tree', None)
                    if current_item and hasattr(project_window.project_tree, 'tree'):
                        item = project_window.project_tree.tree.currentItem()
                        if item and project_window.project_tree.get_item_level(item) >= 2:
                            editor = getattr(project_window.scene_editor, 'editor', None)
                            if editor and hasattr(editor, 'toPlainText'):
                                return editor.toPlainText() or ""
                    return ""
                except Exception:
                    return ""

            def get_scene_summary():
                try:
                    right = getattr(project_window, 'right_stack', None)
                    if right and hasattr(right, 'scene_summary_edit') and right.scene_summary_edit:
                        return right.scene_summary_edit.toPlainText() or ""
                    return ""
                except Exception:
                    return ""

            self.register_collector('scene.fullText', get_scene_full_text)
            self.register_collector('scene.summary', get_scene_summary)

            # Tweaks widget values (additional instructions, output word count)
            if hasattr(right_stack, 'tweaks_widget'):
                tweaks_widget = right_stack.tweaks_widget

                def get_additional_instructions():
                    edit = getattr(tweaks_widget, 'additional_instructions_edit', None)
                    if edit and hasattr(edit, 'toPlainText'):
                        return edit.toPlainText().strip()
                    return ""

                def get_output_word_count():
                    combo = getattr(tweaks_widget, 'output_word_count_combo', None)
                    if combo and hasattr(combo, 'currentText'):
                        text = combo.currentText().strip()
                        return text or "200"
                    return "200"

                self.register_collector('additionalInstructions', get_additional_instructions)
                self.register_collector('outputWordCount', get_output_word_count)
        
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
                if right_stack and hasattr(right_stack, 'get_selected_text_for_prompt'):
                    text = right_stack.get_selected_text_for_prompt()
                    if text:
                        return text

                editor = scene_editor.editor
                if hasattr(editor, 'textCursor'):
                    cursor = editor.textCursor()
                    if cursor.hasSelection():
                        fragment = cursor.selection()
                        return fragment.toPlainText().strip()
                return ""
            self.register_collector('selectedText', get_selected_text)
        
        # User input (will be set dynamically when sending prompts)
        self._user_input_value = ""
        self.register_collector('user_input', lambda: self._user_input_value)

        # Parameterized collectors: wordsBefore and wordsAfter
        def words_before_collector(words: int = 200, fullSentence: bool = True):
            editor = getattr(project_window.scene_editor, 'editor', None)
            if not editor:
                return ""
            try:
                import re
                text = editor.toPlainText()
                cursor = editor.textCursor()
                if cursor.hasSelection():
                    sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
                    end_pos = sel_start
                else:
                    end_pos = cursor.position()

                # Find word spans
                words_spans = [m.span() for m in re.finditer(r"\b\w+\b", text)]
                # Collect words that end before end_pos
                candidate = [s for s in words_spans if s[1] <= end_pos]
                if not candidate:
                    return ""
                selected = candidate[-words:] if len(candidate) >= words else candidate
                start_index = selected[0][0]
                extracted = text[start_index:end_pos]

                if fullSentence:
                    # Determine whether the extract actually begins at a sentence boundary.
                    # We consider punctuation optionally followed by closing quotes as a terminator
                    # e.g. ." ," !" ?"
                    prefix = text[:start_index]
                    # If prefix ends with punctuation possibly followed by quote characters and whitespace,
                    # treat as a sentence boundary and keep the extract. Otherwise drop the partial first sentence.
                    if re.search(r'[.!?,][\"”\']*\s*$', prefix):
                        pass
                    else:
                        # Split into sentences and drop the first (partial) sentence
                        parts = re.split(r'(?<=[.!?])\s+', extracted)
                        if len(parts) > 1:
                            extracted = '\n'.join(parts[1:]).strip()
                        else:
                            # Nothing sensible remains
                            extracted = ''

                return extracted.strip()
            except Exception as e:
                print(f"Error in words_before_collector: {e}")
                return ""

        def words_after_collector(words: int = 200, fullSentence: bool = True):
            editor = getattr(project_window.scene_editor, 'editor', None)
            if not editor:
                return ""
            try:
                import re
                text = editor.toPlainText()
                cursor = editor.textCursor()
                if cursor.hasSelection():
                    sel_end = max(cursor.selectionStart(), cursor.selectionEnd())
                    start_pos = sel_end
                else:
                    start_pos = cursor.position()

                # Find word spans
                words_spans = [m.span() for m in re.finditer(r"\b\w+\b", text)]
                # Collect words that start at or after start_pos
                candidate = [s for s in words_spans if s[0] >= start_pos]
                if not candidate:
                    return ""
                selected = candidate[:words] if len(candidate) >= words else candidate
                end_index = selected[-1][1]
                extracted = text[start_pos:end_index]

                if fullSentence:
                    # If the extracted snippet does not end with sentence punctuation (optionally followed by quotes),
                    # drop the last partial sentence so the result contains only whole sentences.
                    if not re.search(r'[.!?,][\"”\']*\s*$', extracted):
                        parts = re.split(r'(?<=[.!?])\s+', extracted)
                        if len(parts) > 1:
                            extracted = '\n'.join(parts[:-1]).strip()
                        else:
                            extracted = ''

                return extracted.strip()
            except Exception as e:
                print(f"Error in words_after_collector: {e}")
                return ""

        # Register parameterized collectors
        self.register_param_collector('wordsBefore', words_before_collector)
        self.register_param_collector('wordsAfter', words_after_collector)
    
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


def evaluate_variable_expression(expression: str) -> str:
    """Evaluate an expression like 'wordsBefore(200, True)'.

    If the global variable_manager has a param collector for the name, it will be called.
    If no param collector exists, raises KeyError which callers should handle.
    """
    import re
    # Parse name and args
    m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*\((.*)\)\s*$", expression)
    if not m:
        # Not an expression, try non-param collector
        if variable_manager:
            return variable_manager.get_variable(expression)
        return ""

    name = m.group(1)
    args_str = m.group(2).strip()
    args = []
    if args_str:
        # Simple args splitter that handles numbers, booleans, and quoted strings
        parts = [p.strip() for p in re.split(r"(?<!\\),", args_str)]
        for part in parts:
            if re.match(r'^-?\d+$', part):
                args.append(int(part))
            elif part.lower() in ('true', 'false'):
                args.append(part.lower() == 'true')
            else:
                # Strip surrounding quotes if present
                if (part.startswith("\"") and part.endswith("\"")) or (part.startswith("'") and part.endswith("'")):
                    args.append(part[1:-1])
                else:
                    args.append(part)

    if not variable_manager:
        return ""

    try:
        return variable_manager.evaluate_param_variable(name, args)
    except KeyError:
        raise

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