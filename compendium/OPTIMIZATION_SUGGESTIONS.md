# Compendium AI Analysis - Optimization Suggestions

## 1. Prompt Engineering Improvements

### Current Issues:
- Prompt is generic and doesn't leverage story context
- No guidance on entity deduplication
- Lacks instructions for handling temporary vs permanent states
- No validation rules for relationships

### Suggested Enhancements:

```python
def analyze_scene_with_ai(self, include_context=True):
    """Enhanced version with context awareness"""
    
    # Gather additional context
    context = {}
    if include_context and hasattr(self, 'project_window'):
        # Get story metadata
        context['genre'] = self.get_project_setting('genre', 'General Fiction')
        context['pov'] = self.get_current_pov_character()
        context['scene_name'] = self.get_current_scene_name()
        context['previous_scenes'] = self.get_recent_scene_summaries(count=3)
    
    # Use few-shot examples in prompt
    examples = self.get_compendium_examples()
    
    # Enhanced prompt with examples and context
    prompt = self.build_enhanced_prompt(scene_content, context, examples)
```

## 2. JSON Repair Enhancements

### Current Limitations:
- Simple bracket counting doesn't handle nested structures well
- Doesn't handle malformed strings or missing commas
- No validation of content structure

### Suggested Improvements:

```python
def repair_incomplete_json(self, json_str):
    """Enhanced JSON repair with better heuristics"""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Try multiple repair strategies
        strategies = [
            self.repair_with_jsonrepair,  # Use jsonrepair library
            self.repair_with_regex,       # Regex-based fixes
            self.repair_with_ast,         # AST-based parsing
            self.repair_with_llm,         # Ask LLM to fix its own JSON
        ]
        
        for strategy in strategies:
            try:
                repaired = strategy(json_str, e)
                json.loads(repaired)  # Validate
                return repaired
            except:
                continue
        
        # Last resort: extract partial data
        return self.extract_partial_json(json_str)

def repair_with_llm(self, json_str, error):
    """Ask the LLM to fix its own malformed JSON"""
    repair_prompt = f"""The following JSON is malformed. Fix it and return only valid JSON:

Error: {error}

Malformed JSON:
{json_str}

Fixed JSON:"""
    
    response = WWApiAggregator.send_prompt_to_llm(
        repair_prompt, 
        overrides={'max_tokens': 2000, 'temperature': 0}
    )
    return self.preprocess_json_string(response)
```

## 3. Streaming and Progress Feedback

### Enhancement: Stream AI responses

```python
def analyze_scene_with_ai_streaming(self):
    """Analyze with streaming support and progress indicator"""
    from PyQt5.QtWidgets import QProgressDialog
    
    # Show progress dialog
    progress = QProgressDialog(
        "Analyzing scene with AI...", 
        "Cancel", 
        0, 100, 
        self
    )
    progress.setWindowModality(Qt.WindowModal)
    progress.show()
    
    accumulated_response = ""
    
    def on_chunk(chunk, progress_pct):
        nonlocal accumulated_response
        accumulated_response += chunk
        progress.setValue(int(progress_pct * 100))
        
        # Try to parse partial JSON
        try:
            partial = self.extract_partial_json(accumulated_response)
            # Update preview in dialog
            preview_dialog.update_preview(partial)
        except:
            pass
    
    # Stream response
    response = WWApiAggregator.send_prompt_streaming(
        prompt, 
        callback=on_chunk,
        overrides=overrides
    )
    
    progress.close()
```

## 4. Intelligent Merging Strategy

### Current Issue:
- Simple overwrite can lose user customizations
- No conflict resolution
- No tracking of AI vs manual changes

### Suggested Enhancement:

```python
def save_ai_analysis_with_conflict_resolution(self, ai_compendium):
    """Smart merge with conflict detection"""
    
    conflicts = []
    
    for new_cat in ai_compendium.get("categories", []):
        for new_entry in new_cat.get("entries", []):
            entry_name = new_entry["name"]
            
            # Check if entry was manually modified
            if self.is_manually_modified(entry_name):
                conflict = {
                    'entry': entry_name,
                    'existing': self.get_existing_entry(entry_name),
                    'ai_suggestion': new_entry,
                    'last_modified': self.get_last_modified(entry_name)
                }
                conflicts.append(conflict)
    
    # If conflicts exist, show resolution dialog
    if conflicts:
        resolution_dialog = ConflictResolutionDialog(conflicts, self)
        if resolution_dialog.exec_() != QDialog.Accepted:
            return
        resolved = resolution_dialog.get_resolutions()
        ai_compendium = self.apply_resolutions(ai_compendium, resolved)
    
    # Proceed with merge
    self.merge_compendium(ai_compendium)

def is_manually_modified(self, entry_name):
    """Check if entry has manual changes"""
    metadata = self.get_entry_metadata(entry_name)
    return metadata.get('last_modified_by') == 'user'
```

## 5. Batch Analysis

### Enhancement: Analyze multiple scenes

```python
def analyze_multiple_scenes(self, scene_ids):
    """Batch analyze multiple scenes efficiently"""
    
    # Combine scenes with separators
    combined_scenes = []
    for scene_id in scene_ids:
        scene = self.get_scene_content(scene_id)
        combined_scenes.append(f"### Scene: {scene_id}\n{scene}")
    
    scene_content = "\n\n---\n\n".join(combined_scenes)
    
    # Enhanced prompt for multiple scenes
    prompt = f"""Analyze ALL scenes below and extract comprehensive compendium data.
Pay attention to character development across scenes.

{scene_content}"""
    
    # Process with higher token limit
    overrides = {
        'max_tokens': 8000,
        'temperature': 0.3
    }
    
    return self.analyze_with_prompt(prompt, overrides)
```

## 6. Caching and Incremental Updates

### Enhancement: Only analyze new/changed content

```python
def analyze_scene_incremental(self):
    """Only analyze changes since last analysis"""
    
    # Get hash of current scene
    scene_hash = self.get_scene_hash(scene_content)
    last_hash = self.get_last_analysis_hash()
    
    if scene_hash == last_hash:
        QMessageBox.information(
            self, 
            "Already Analyzed", 
            "This scene has already been analyzed."
        )
        return
    
    # Get diff if available
    if last_hash:
        diff = self.get_scene_diff(last_hash, scene_hash)
        prompt = f"Analyze only the CHANGED portions:\n{diff}"
    else:
        prompt = f"Analyze full scene:\n{scene_content}"
    
    # Cache result
    result = self.analyze_with_prompt(prompt)
    self.cache_analysis_result(scene_hash, result)
```

## 7. Quality Validation

### Enhancement: Validate AI output quality

```python
def validate_ai_compendium(self, ai_compendium):
    """Validate AI output before showing to user"""
    
    issues = []
    
    for cat in ai_compendium.get("categories", []):
        for entry in cat.get("entries", []):
            # Check for placeholder text
            if "description" in entry.get("content", "").lower():
                issues.append(f"Placeholder text in {entry['name']}")
            
            # Check for overly long content
            if len(entry.get("content", "")) > 1000:
                issues.append(f"Overly detailed entry: {entry['name']}")
            
            # Check for duplicate names
            if self.is_duplicate_entry(entry["name"]):
                issues.append(f"Possible duplicate: {entry['name']}")
            
            # Validate relationships exist
            for rel in entry.get("relationships", []):
                if not self.entry_exists(rel["name"]):
                    issues.append(f"Invalid relationship: {entry['name']} -> {rel['name']}")
    
    if issues:
        # Show warning dialog with issues
        dialog = ValidationIssuesDialog(issues, self)
        dialog.exec_()
    
    return len(issues) == 0
```

## 8. Template-Based Extraction

### Enhancement: Use structured templates per category

```python
CATEGORY_TEMPLATES = {
    "Characters": {
        "required_fields": ["name", "role"],
        "optional_fields": ["age", "appearance", "personality", "backstory"],
        "max_content_length": 500,
        "example": {
            "name": "John Smith",
            "content": "A 35-year-old detective with a troubled past...",
            "role": "protagonist"
        }
    },
    "Locations": {
        "required_fields": ["name", "type"],
        "optional_fields": ["atmosphere", "significance"],
        "max_content_length": 300,
    }
}

def build_category_specific_prompt(self, category_name):
    """Build targeted prompts for specific categories"""
    template = CATEGORY_TEMPLATES.get(category_name)
    
    prompt = f"""Extract ONLY {category_name} from the scene.

Required fields: {', '.join(template['required_fields'])}
Optional fields: {', '.join(template['optional_fields'])}
Max content length: {template['max_content_length']} characters

Example:
{json.dumps(template['example'], indent=2)}

Scene:
{{scene_content}}

Output (JSON only):"""
    
    return prompt
```

## 9. User Feedback Loop

### Enhancement: Learn from user corrections

```python
def track_user_corrections(self, original_ai_data, user_corrected_data):
    """Track how users modify AI suggestions to improve future prompts"""
    
    corrections = []
    
    for ai_entry, user_entry in zip(original_ai_data, user_corrected_data):
        if ai_entry != user_entry:
            correction = {
                'original': ai_entry,
                'corrected': user_entry,
                'timestamp': datetime.now(),
                'correction_type': self.classify_correction(ai_entry, user_entry)
            }
            corrections.append(correction)
    
    # Store corrections
    self.save_corrections_to_db(corrections)
    
    # Periodically analyze corrections to improve prompts
    if len(self.get_all_corrections()) > 50:
        self.update_prompt_based_on_corrections()
```

## 10. Export/Import Analysis Results

### Enhancement: Allow sharing AI analysis results

```python
def export_analysis_result(self):
    """Export AI analysis for review or sharing"""
    
    file_path, _ = QFileDialog.getSaveFileName(
        self, 
        "Export Analysis", 
        "", 
        "JSON Files (*.json);;Markdown (*.md)"
    )
    
    if not file_path:
        return
    
    if file_path.endswith('.md'):
        # Export as readable markdown
        self.export_as_markdown(file_path)
    else:
        # Export as JSON
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.ai_compendium_data, f, indent=2)

def export_as_markdown(self, file_path):
    """Export compendium as readable markdown"""
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("# Compendium Analysis\n\n")
        
        for cat in self.ai_compendium_data.get("categories", []):
            f.write(f"## {cat['name']}\n\n")
            
            for entry in cat.get("entries", []):
                f.write(f"### {entry['name']}\n\n")
                f.write(f"{entry['content']}\n\n")
                
                if entry.get("relationships"):
                    f.write("**Relationships:**\n")
                    for rel in entry["relationships"]:
                        f.write(f"- {rel['name']}: {rel['type']}\n")
                    f.write("\n")
```

## Summary of Key Improvements

1. **Context-Aware Prompts**: Use story metadata, genre, POV
2. **Better JSON Repair**: Multiple strategies including LLM self-repair
3. **Streaming Support**: Real-time progress and preview
4. **Conflict Resolution**: Handle manual vs AI changes
5. **Batch Processing**: Analyze multiple scenes efficiently
6. **Incremental Updates**: Only analyze changed content
7. **Quality Validation**: Validate AI output automatically
8. **Template-Based**: Structured extraction per category
9. **Learning System**: Improve from user corrections
10. **Export/Import**: Share and review analyses

## Implementation Priority

**High Priority:**
1. Enhanced prompts with context (immediate quality improvement)
2. Better JSON repair with jsonrepair library
3. Quality validation before showing to user

**Medium Priority:**
4. Streaming support (better UX)
5. Conflict resolution for merges
6. Batch analysis capabilities

**Low Priority:**
7. Incremental updates (optimization)
8. Learning from corrections (long-term)
9. Export/import features (nice-to-have)
