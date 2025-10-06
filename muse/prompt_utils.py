import json
import os
from typing import Dict, List, Optional

from settings.settings_manager import WWSettingsManager

def get_prompt_categories() -> List[str]:
    """Return the list of supported prompt categories."""
    return ["Workshop", "Summary", "Prose", "Rewrite"]

def get_workshop_prompts() -> List[Dict]:
    """Load workshop prompts from the global prompts file for backward compatibility."""
    return load_prompts("Workshop")

def load_project_options(project_name: str) -> Dict:
    """Load project options to inject dynamic values into default prompts."""
    options = {}
    project_settings_file = "project_settings.json"
    filepath = WWSettingsManager.get_project_path(file=project_settings_file)
    
    if not os.path.exists(filepath):
        oldpath = os.path.join(os.getcwd(), project_settings_file)
        if os.path.exists(oldpath):
            os.rename(oldpath, filepath)

    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_settings = json.load(f)
            options = all_settings.get(project_name, {})
        except Exception as e:
            print(f"Error loading project options: {e}")
    return options

def get_default_prompt(style: str) -> Dict:
    """Generate a default prompt configuration for the given style."""
    default_prompts = {
        "Prose": _("You are collaborating with the author to write a scene. Write the scene in {pov} point of view, from the perspective of {pov_character}, and in {tense}."),
        "Summary": _("Summarize the following chapter for use in a story prompt, covering Goal, Key Events, Character Dev, Info Revealed, Emotional Arc, and Plot Setup. Be conscientious of token usage."),
        "Rewrite": _("Rewrite the passage for clarity."),
        "Workshop": _("I need your help with my project. Please provide creative brainstorming and ideas."),
    }
    return {
        "name": _("Default {} Prompt").format(style),
        "messages": [
            {
                "role": "system",
                "content": default_prompts.get(style, "")
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.7,
        "default": True,
        "type": "prompt",
        "id": f"default_{style.lower()}"
    }

def load_prompts(style: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Load prompts from the prompts.json file."""
    try:
        data = _load_prompt_style(style)
        if style:
            return _normalize_prompt_collection(data)
        return {category: _normalize_prompt_collection(prompts)
                for category, prompts in data.items()}
    except Exception as e:
        print(f"Error loading {style or 'all'} prompts: {e}")
        return {} if not style else _normalize_prompt_collection([get_default_prompt(style)])

def save_prompts(prompts_data: Dict[str, List[Dict]], prompts_file: str, backup_file: str) -> bool:
    """Save prompts to the specified file and create a backup."""
    try:
        normalized = {category: _normalize_prompt_collection(prompts)
                      for category, prompts in prompts_data.items()}
        with open(prompts_file, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=4)
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving prompts: {e}")
        return False

def _load_prompt_style(style: Optional[str]) -> Dict[str, List[Dict]]:
    """Load prompts for a specific style or all styles from prompts.json."""
    filepath = WWSettingsManager.get_project_path(file="prompts.json")
    data = {}
    
    if not os.path.exists(filepath):
        oldpath = "prompts.json"
        if os.path.exists(oldpath):
            os.rename(oldpath, filepath)
    
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

    if style:
        return data.get(style, [])
    return data


def _normalize_prompt_collection(prompts: List[Dict]) -> List[Dict]:
    """Ensure each prompt contains a messages list and no legacy text field."""
    normalized: List[Dict] = []
    for prompt in prompts or []:
        prompt_copy = dict(prompt)
        text_value = prompt_copy.pop("text", None)

        messages = prompt_copy.get("messages") or []
        if not messages and text_value is not None:
            messages = [{"role": "system", "content": text_value}]

        normalized_messages: List[Dict] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role", "system")
            content = message.get("content", message.get("text", ""))
            normalized_messages.append({
                "role": role,
                "content": content
            })

        if not normalized_messages:
            normalized_messages.append({"role": "system", "content": text_value or ""})

        prompt_copy["messages"] = normalized_messages
        normalized.append(prompt_copy)

    return normalized