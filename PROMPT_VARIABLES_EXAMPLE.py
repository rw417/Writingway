# Example: How to use the new prompt variable system in Writingway

"""
This file shows how to use the new centralized prompt variable system.
You can now easily add variables that can be referenced in prompts using {variableName}.

Built-in Variables (automatically available):
- {pov} - Current POV setting (First Person, Third Person Limited, etc.)
- {pov_character} - Current POV character name
- {tense} - Current tense setting (Past Tense, Present Tense, etc.)
- {story_so_far} - Current scene text (if editing a scene)
- {instructions} - Action beats text
- {context} - Selected context from compendium
- {user_input} - Input passed when sending prompt
- {selectedText} - Currently selected text in editor
- {projectName} - Name of current project
- {currentDate} - Current date
- {wordCount} - Word count of current scene

Example Usage in Prompts:
"""

# Example prompt content that uses variables:
example_prompt = """
You are helping {pov_character} write a story in {pov} point of view, using {tense}.

Project: {projectName}
Current scene word count: {wordCount}
Date: {currentDate}

Current story so far:
{story_so_far}

Selected text to work with:
{selectedText}

Action beats to incorporate:
{instructions}

Additional context:
{context}

User request: {user_input}

Please help improve this scene.
"""

# How to add custom variables in your code:

def add_custom_variables_example(project_window):
    """Example of how to add custom variables."""
    
    # Add a static variable
    project_window.add_prompt_variable('authorName', 'Jane Smith')
    
    # Add a dynamic variable that changes based on current state
    def get_character_count():
        if hasattr(project_window, 'scene_editor'):
            text = project_window.scene_editor.editor.toPlainText()
            return str(len(text))
        return "0"
    
    project_window.add_prompt_variable('characterCount', get_character_count)
    
    # Add a variable that depends on current selection
    def get_current_chapter():
        current_item = project_window.project_tree.tree.currentItem()
        if current_item:
            # Walk up to find chapter level
            while current_item.parent():
                current_item = current_item.parent()
            return current_item.text(0)
        return "Unknown Chapter"
    
    project_window.add_prompt_variable('currentChapter', get_current_chapter)

# How variables work in the prompt system:

def example_prompt_usage():
    """
    When you create a prompt with content like:
    
    "Rewrite this text in {tense} from {pov_character}'s perspective: {selectedText}"
    
    The system will automatically:
    1. Collect current values for all variables
    2. Replace {tense} with current tense setting
    3. Replace {pov_character} with current POV character
    4. Replace {selectedText} with currently selected text
    5. Send the formatted prompt to LLM
    
    If a variable is missing, it will show an error like:
    "Rewrite this text in Past Tense from {ERROR: 'badVar' not found}'s perspective: Hello world"
    
    Note: Other variables still work even if some are missing!
    """
    pass

# Error handling example:

def error_handling_example():
    """
    Example of how the system handles missing variables:
    
    Prompt content: "Write in {pov} about {unknownVar} using {tense}."
    Available vars: {"pov": "First Person", "tense": "Present"}
    
    Result: "Write in First Person about {ERROR: 'unknownVar' not found} using Present."
    
    Benefits:
    - Valid variables (pov, tense) still work
    - Clear error message for missing variable
    - Prompt remains functional
    - Easy to spot and fix variable name typos
    """
    pass

# Migration from old system:

def migration_notes():
    """
    Old way (in get_additional_vars):
    return {
        "pov": self.pov_combo.currentText(),
        "instructions": self.prompt_input.toPlainText(),
        # ... etc
    }
    
    New way:
    - Variables are automatically collected
    - Just reference them in prompts as {variableName}
    - Add custom variables using project_window.add_prompt_variable()
    - System handles UI integration automatically
    """
    pass