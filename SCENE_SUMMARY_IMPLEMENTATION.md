# Scene Summary Feature - Complete Implementation Summary

## Overview
This document describes the complete overhaul of the scene summary feature, including POV/tense storage per scene and chapter-level batch summary generation.

## Key Changes

### 1. Fixed Read-Only Editor Issue ✅
- **Scene pages (level >= 2)**: Editor is now editable (`editor.setReadOnly(False)`)
- **Chapter pages (level == 1)**: Editor remains read-only (displays combined scene summaries)
- **Act pages (level == 0)**: Editor is editable for act summaries

### 2. POV/Tense Storage Per Scene ✅

#### Data Structure
Each scene in the structure JSON now has three additional fields:
```json
{
  "name": "Scene 1",
  "uuid": "...",
  "latest_file": "...",
  "summary": "...",
  "pov": "Third Person Limited",
  "pov_character": "Alice",
  "tense": "Past Tense"
}
```

#### Automatic Saving
- POV/tense combo box changes automatically save to the active scene's structure
- Implemented in:
  - `handle_pov_change()` - calls `_save_scene_pov_tense()`
  - `handle_tense_change()` - calls `_save_scene_pov_tense()`
  - `handle_pov_character_change()` - calls `_save_scene_pov_tense()`

#### Automatic Loading
- When a scene is loaded, POV/tense values are populated from the scene's stored data
- If no stored values exist, current combo box values are used and saved
- Implemented in `_load_scene_pov_tense()`

#### Prompt Variables Updated
The prompt variable system (`muse/prompt_variables.py`) now:
1. Checks if the current item is a scene (level >= 2)
2. If yes, pulls POV/tense from the scene's structure JSON
3. If no or not found, falls back to combo box values
4. This enables batch processing to use each scene's individual POV/tense values

### 3. Chapter Summary Generation ✅

#### New UI Component: ChapterSummaryPanel
Created `project_window/chapter_summary_panel.py` with:
- **Prompt Panel**: Uses "Summary" category prompts
- **Preview Button**: Preview the prompt (icon: eye)
- **Refresh Button**: Reload prompts (icon: refresh)
- **Send Button**: Generate summaries (icon: send)
- **Stop Button**: Stop generation (icon: x-octagon)
- **Overwrite Checkbox**: "Overwrite Existing Scene Summaries" (default: unchecked)

#### Chapter Summary Display
- Chapter summaries are **dynamically built** from scene summaries in real-time
- No "summary" field is stored at chapter level in the JSON
- Format: `Scene Name\nScene Summary\n\nNext Scene Name\n...`
- Implemented in `_build_chapter_summary()`

#### POV/Tense Controls Hidden on Chapter Pages
- The `top_control_container` (POV/tense combo boxes) is hidden when viewing chapters
- Shown when viewing scenes
- Also hidden on act pages

#### Batch Summary Generation
When the user clicks "Send" on a chapter page:

1. **Collect Scenes to Process**:
   - If "Overwrite" is unchecked: Only scenes with empty summaries
   - If "Overwrite" is checked: All scenes in the chapter

2. **For Each Scene**:
   - Load scene content from file
   - Get scene's POV/tense from structure JSON
   - Build prompt variables with scene-specific data
   - Render prompt using Jinja2
   - Send to LLM with scene's specific configuration
   - Stream response and accumulate in scene's "summary" field
   - Save structure JSON after each scene completes

3. **Processing Flow**:
   - Scenes are processed sequentially (one at a time)
   - Uses `LLMWorker` for async LLM communication
   - No progress dialog (silent processing)
   - Chapter summary display refreshes automatically when complete

### 4. Implementation Details

#### Files Modified

**`project_window/project_window.py`:**
- Added `_load_scene_pov_tense()` - Load POV/tense from scene structure or save current values
- Added `_save_scene_pov_tense()` - Save POV/tense to active scene's structure
- Updated `handle_pov_change()` - Calls `_save_scene_pov_tense()`
- Updated `handle_tense_change()` - Calls `_save_scene_pov_tense()`
- Updated `handle_pov_character_change()` - Calls `_save_scene_pov_tense()`
- Updated `load_current_item_content()` - Sets editor read-only state correctly, hides/shows POV controls

**`project_window/right_stack.py`:**
- Imported `ChapterSummaryPanel`
- Updated `create_summary_panel()` - Creates chapter summary panel with controls
- Added `_generate_chapter_summaries()` - Entry point for batch generation
- Added `_start_batch_summary_generation()` - Initialize batch processing
- Added `_process_next_batch_scene()` - Process one scene at a time
- Added `_on_batch_scene_summary_received()` - Accumulate LLM response
- Added `_on_batch_scene_finished()` - Move to next scene
- Added `_stop_chapter_summary_generation()` - Stop processing
- Added `_preview_chapter_summary_prompt()` - Preview prompt (stub)
- Added `_refresh_chapter_summary_prompt()` - Refresh prompts

**`muse/prompt_variables.py`:**
- Updated `get_pov()` - Pull from scene structure if available
- Updated `get_pov_character()` - Pull from scene structure if available
- Updated `get_tense()` - Pull from scene structure if available

**Files Created:**
- `project_window/chapter_summary_panel.py` - New UI panel for chapter summary controls

### 5. User Workflow

#### For Individual Scenes:
1. Select a scene in the project tree
2. The `scene_summary_edit` text box shows the scene's summary
3. User can:
   - Type manually into the summary box (auto-saves)
   - Use the "Summarize" tab in the LLM panel to generate with LLM
   - Change POV/tense (auto-saves to scene structure)

#### For Chapters:
1. Select a chapter in the project tree
2. Main editor shows read-only combined scene summaries
3. Right panel shows Chapter Summary controls
4. User workflow:
   - Select a Summary prompt
   - (Optional) Check "Overwrite Existing Scene Summaries"
   - Click Send button
   - System processes each scene:
     - Loads scene content
     - Uses scene's POV/tense values
     - Generates summary with LLM
     - Saves to scene structure
   - Chapter display auto-refreshes with new summaries

#### For Acts:
1. Select an act in the project tree
2. Main editor is editable for act summaries
3. POV/tense controls are hidden (acts don't have individual POV/tense)

### 6. Technical Notes

#### Prompt Variables in Batch Mode
When generating summaries from a chapter page, the system:
- Creates a temporary variables dict for each scene
- Includes scene-specific `pov`, `pov_character`, `tense`
- Includes `scene.fullText` with the scene's content
- Does NOT use global/UI combo box values
- Each scene is treated independently

#### Scene Content Loading
- Uses `model.load_scene_content(hierarchy)` to load from HTML files
- Converts HTML to plain text for summarization
- Skips scenes with no content

#### LLM Worker Management
- Creates one `LLMWorker` instance per scene
- Workers are created sequentially (not in parallel)
- Each worker is cleaned up after completion
- Stop button terminates current worker

#### Structure JSON Persistence
- `model.save_structure()` is called after each scene summary is generated
- Ensures summaries are persisted immediately
- Chapter summaries are NOT stored - built dynamically on display

## Migration Notes

### Existing Projects
- Scenes without POV/tense values will use current combo box values on first load
- Values are then saved to structure JSON
- Existing scene summaries are preserved
- Chapter "summary" fields in JSON are ignored (built dynamically)

### Backward Compatibility
- Old projects will work seamlessly
- POV/tense fields are added automatically when scenes are first loaded
- No manual migration needed

## Testing Checklist

- [ ] Scene editor is editable on scene pages
- [ ] Scene editor is read-only on chapter pages
- [ ] POV/tense combo boxes are hidden on chapter/act pages
- [ ] POV/tense combo boxes are visible on scene pages
- [ ] Changing POV saves to scene structure JSON
- [ ] Changing tense saves to scene structure JSON
- [ ] Loading a scene populates POV/tense from structure
- [ ] Chapter summary display combines all scene summaries
- [ ] Chapter summary "Send" button generates summaries
- [ ] "Overwrite" checkbox works correctly
- [ ] Each scene uses its own POV/tense in prompt variables
- [ ] Scene summaries are saved to structure JSON
- [ ] Batch generation stops when "Stop" button is clicked
- [ ] Chapter display refreshes after batch generation completes

## Files Summary

### Modified Files:
1. `project_window/project_window.py` - Main window logic, POV/tense save/load
2. `project_window/right_stack.py` - Chapter summary panel and batch generation
3. `muse/prompt_variables.py` - Pull POV/tense from scene structure

### Created Files:
1. `project_window/chapter_summary_panel.py` - Chapter summary UI panel

### Backup Files (Disabled):
1. `project_window/summary_controller.py.bak`
2. `project_window/summary_model.py.bak`
3. `project_window/summary_service.py.bak`

## Known Limitations

1. No progress feedback during batch generation
2. Preview button on chapter page is not yet implemented
3. Scenes are processed sequentially (not in parallel)
4. No retry mechanism if LLM call fails for a scene
5. Chapter summaries are not stored (rebuilt on each view)

## Future Enhancements

1. Add progress indicator for batch generation
2. Implement preview functionality for chapter summaries
3. Add parallel processing option
4. Add error handling and retry logic
5. Option to cache chapter summaries
6. Add rate limiting between LLM calls
