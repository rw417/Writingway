# Prompt Preview Dialog Refactoring

## Overview
The prompt preview dialog has been refactored into a tabbed interface with separate components for better organization and maintainability.

## New Structure

### 1. Tabbed Dialog Container
**File**: `muse/prompt_dialog_tabbed.py` + `ui_files/dialogs/prompt_dialog_tabbed.ui`

The main dialog now contains two tabs:
- **Tweaks Tab**: For additional prompt parameters
- **Preview Tab**: For viewing and editing the assembled prompt

Key features:
- Automatically refreshes Preview when switching to that tab
- Merges tweak values into the prompt variables
- Preserves all existing functionality from the original PromptPreviewDialog

### 2. Tweaks Widget
**Files**: `muse/tweaks_widget.py` + `ui_files/dialogs/tweaks_widget.ui`

Contains input controls for additional prompt tweaks:
- **Additional Instructions**: Multi-line text box for supplemental guidance
- **Output Word Count**: Editable combo box (100, 200, 400) with default 200

Methods:
- `get_tweak_values()`: Returns dict of current tweak values
- `set_tweak_values(values)`: Sets tweak inputs from dict
- `clear_tweaks()`: Resets all inputs to defaults

### 3. Preview Widget
**Files**: `muse/preview_widget.py` + `ui_files/dialogs/preview_widget.ui`

Extracted from the original PromptPreviewDialog. Contains all the message tree functionality:
- Message list with role selectors
- Add/delete message controls
- Zoom in/out functionality
- Token counting
- Manual editing of messages
- Send prompt button

Methods:
- `set_prompt_data(...)`: Sets the prompt data to display
- `refresh_preview(tweak_overrides)`: Rebuilds the tree with updated variables
- `get_edited_content()`: Collects edited messages
- Signals: `sendPromptRequested`, `returnRequested`

### 4. Legacy Wrapper
**File**: `muse/prompt_preview_dialog.py`

Simple inheritance wrapper that maintains backwards compatibility:
```python
class PromptPreviewDialog(PromptDialogTabbed):
    pass
```

This ensures existing code continues to work without changes.

## New Prompt Variables

Two new variables have been added to the prompt system:

| Variable | Description | Default | Source |
|----------|-------------|---------|--------|
| `{additionalInstructions}` | Extra guidance from Tweaks tab | "" | TweaksWidget text box |
| `{outputWordCount}` | Target output length | "200" | TweaksWidget combo box |

These variables are registered in `prompt_variables.py` and documented in:
- `PROMPT_VARIABLES_DOCS.md`
- `PROMPT_VARIABLES_EXAMPLE.py`

## Workflow

1. User opens dialog (via existing `PromptPreviewDialog` import)
2. Dialog opens to **Tweaks** tab
3. User can:
   - Enter additional instructions
   - Set target word count
   - Switch to **Preview** tab to see assembled prompt
4. When switching to **Preview**:
   - `on_tab_changed()` fires
   - Tweak values are collected
   - Preview refreshes with merged variables
5. User can manually edit messages in Preview
6. Clicking **Send** emits the edited prompt config
7. Main window receives signal and sends to LLM

## Migration Notes

### For Users
- No changes needed! Existing code using `PromptPreviewDialog` works as-is
- New tweak variables available in all prompts: `{additionalInstructions}` and `{outputWordCount}`

### For Developers
If creating new dialogs, use `PromptDialogTabbed` directly:
```python
from muse.prompt_dialog_tabbed import PromptDialogTabbed

dialog = PromptDialogTabbed(
    self.controller,
    prompt_config=config,
    user_input=input_text,
    additional_vars=vars_dict,
    parent=self
)
dialog.promptConfigReady.connect(self.handle_prompt)
dialog.exec_()
```

## Benefits

1. **Better Organization**: Separate UI and logic files for each component
2. **Easier Maintenance**: Smaller, focused files instead of one large dialog
3. **Extensible**: Easy to add new tweak controls without touching preview logic
4. **Backwards Compatible**: No changes needed to existing code
5. **Variable Integration**: Tweaks automatically merge into prompt variable system
