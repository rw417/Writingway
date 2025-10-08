import json
import re
from typing import Optional, Tuple, Dict, Any

from settings.llm_api_aggregator import WWApiAggregator


def preprocess_json_string(raw_string: str) -> str:
    """Remove markdown code fences from JSON response."""
    cleaned = re.sub(r'^```(?:json)?\s*\n', '', raw_string, flags=re.MULTILINE)
    cleaned = re.sub(r'\n```$', '', cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def repair_incomplete_json(json_str: str) -> Optional[str]:
    """Attempt to repair incomplete JSON by closing brackets.

    Returns the repaired JSON string or None if not repairable.
    """
    try:
        json.loads(json_str)
        return json_str
    except json.JSONDecodeError:
        repaired = json_str.strip()
        if repaired.endswith('"'):
            repaired += '"'
        open_braces = repaired.count('{') - repaired.count('}')
        open_brackets = repaired.count('[') - repaired.count(']')
        for _ in range(open_braces):
            repaired += '}'
        for _ in range(open_brackets):
            repaired += ']'
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError:
            return None


def analyze_scene_with_llm(prompt: str, overrides: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Send prompt to the LLM using WWApiAggregator and return (success, response_text or error)."""
    try:
        response = WWApiAggregator.send_prompt_to_llm(prompt, overrides=overrides)
        return True, response
    except Exception as e:
        return False, str(e)
