# Prompt Variable System Documentation

## Overview

Writingway now has a centralized prompt variable system that makes it easy to add and use variables in your prompts. Instead of manually managing variables in multiple places, the system automatically collects all available variables and makes them available for use in prompt templates.

## Built-in Variables

The following variables are automatically available in all prompts:

| Variable | Description | Example Value |
|----------|-------------|---------------|
| `{pov}` | Current POV setting | "Third Person Limited" |
| `{pov_character}` | Current POV character | "Alice" |
| `{tense}` | Current tense setting | "Past Tense" |
| `{story_so_far}` | Current scene text | The full text of current scene |
| `{sceneBeat}` | Action beats text | User's action beats input |
| `{context}` | Selected context from compendium | Selected compendium entries |
| `{user_input}` | Input passed when sending prompt | Varies by context |
| `{selectedText}` | Currently selected text in editor | Any selected text |
| `{projectName}` | Name of current project | "My Novel" |
| `{currentDate}` | Current date | "2025-10-06" |
| `{wordCount}` | Word count of current scene | "1,247" |
| `{additionalInstructions}` | Additional instructions from Tweaks tab | User's supplemental guidance |
| `{outputWordCount}` | Target word count from Tweaks tab | "200" |

## Using Variables in Prompts

Simply reference any variable in your prompt content using curly braces:

```
You are helping to write a story in {pov} from {pov_character}'s perspective.

Current scene ({wordCount} words):
{story_so_far}

Selected text to rewrite:
{selectedText}

Instructions: {instructions}

Please rewrite the selected text in {tense}.
```

## Adding Custom Variables

### Method 1: Static Variables

Add a variable with a fixed value:

```python
project_window.add_prompt_variable('authorName', 'Jane Smith')
project_window.add_prompt_variable('genre', 'Fantasy')
```

### Method 2: Dynamic Variables

Add a variable that changes based on current state:

```python
def get_scene_count():
    # Your logic to count scenes
    return str(len(all_scenes))

project_window.add_prompt_variable('sceneCount', get_scene_count)
```

### Method 3: Using Variable Manager Directly

For more advanced cases:

```python
from muse.prompt_variables import get_variable_manager

manager = get_variable_manager()
if manager:
    # Add a custom variable
    manager.add_custom_variable('customVar', lambda: "some value")
    
    # Get current value of a variable
    current_pov = manager.get_variable('pov')
    
    # Get all variables
    all_vars = manager.get_all_variables()
```

## Examples

### Rewriting Prompt
```
Rewrite the following text to be more {adjective} while maintaining the {tense} and {pov} perspective:

{selectedText}

Target length: approximately {outputWordCount} words.

Additional guidance: {additionalInstructions}

Make sure the rewrite fits the tone of: {projectName}
```

### Character Development Prompt  
```
Analyze {pov_character}'s character development in this {wordCount}-word scene:

{story_so_far}

Consider the context: {context}
```

### Scene Enhancement Prompt
```
Enhance this scene for {projectName} (written {currentDate}):

Current scene in {tense}, {pov}:
{story_so_far}

Action beats to incorporate:
{sceneBeat}

Selected text that needs special attention:
{selectedText}

Additional instructions: {additionalInstructions}
Target length: {outputWordCount} words
```

## Benefits

1. **Centralized Management**: All variables in one place
2. **Automatic Collection**: No need to manually gather variables
3. **Easy Extension**: Simple API to add new variables
4. **UI Integration**: Variables automatically update based on UI state
5. **Legacy Compatibility**: Old prompts still work

## Migration Guide

### Old Way (Manual)
```python
def get_additional_vars(self):
    return {
        "pov": self.pov_combo.currentText(),
        "sceneBeat": self.prompt_input.toPlainText(),
        # ... manual collection
    }
```

### New Way (Automatic)
Variables are automatically collected. Just reference them in prompts:
```
Write in {pov} using these instructions: {instructions}
```

To add custom variables:
```python
project_window.add_prompt_variable('myVar', 'myValue')
```

## Technical Details

- Variables are collected just-in-time when prompts are assembled
- UI components are automatically integrated
- Missing variables are handled gracefully with clear error messages
- Individual variable errors don't break other variables in the same prompt
- Error handling prevents crashes from invalid variable functions
- Memory efficient - no unnecessary variable storage

## Error Handling

When a variable is missing or invalid, the system:

1. **Shows clear error messages**: `{ERROR: 'variableName' not found}`
2. **Continues processing other variables**: Valid variables still work
3. **Logs warnings**: Missing variables are logged for debugging
4. **Maintains prompt functionality**: Prompts remain usable even with errors

Example with missing variables:
```
Input:  "Write in {pov} from {badVar}'s perspective using {tense}."
Variables: {"pov": "Third Person", "tense": "Past Tense"}
Result: "Write in Third Person from {ERROR: 'badVar' not found}'s perspective using Past Tense."
```