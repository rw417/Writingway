import json
import re
import logging
from typing import Optional, Tuple, Dict, Any

from settings.llm_api_aggregator import WWApiAggregator
from langchain.prompts import PromptTemplate

logger = logging.getLogger(__name__)


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


def analyze_scene(scene_content: str, existing_compendium: Dict[str, Any], overrides: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Run the scene analysis end-to-end against the LLM and return parsed JSON.

    Returns a tuple: (success, parsed_compendium_dict_or_None, error_message_or_None)
    """
    if context is None:
        context = {}

    # Build the prompt template (kept in sync with the UI caller)
    analysis_template = PromptTemplate(
        input_variables=["scene_content", "existing_compendium", "context"],
        template=(
            "You are a creative writing assistant analyzing a scene to extract worldbuilding information.\n\n"
            "TASK: Extract entities from the scene and format them as JSON compendium entries.\n\n"
            "CONTEXT:\n"
            "- Story Genre: {context.get(\"genre\", \"General Fiction\")}\n"
            "- Current Chapter/Scene: {context.get(\"scene_name\", \"Unknown\")}\n"
            "- POV Character: {context.get(\"pov\", \"Unknown\")}\n\n"
            "RULES:\n"
            "1. Extract only FACTUAL information (no speculation)\n"
            "2. Focus on timeless traits, not temporary states\n"
            "3. For existing entries, only add NEW information\n"
            "4. Keep descriptions concise (2-3 sentences max)\n"
            "5. Use consistent naming (check existing entries first)\n\n"
            "CATEGORIES TO EXTRACT:\n"
            "- Characters: Name, age, appearance, personality, role, key traits\n"
            "- Locations: Name, type (city/room/etc), atmosphere, significance\n"
            "- Objects: Name, description, importance to plot\n"
            "- Factions/Groups: Name, purpose, members, relationships\n"
            "- Events: Name, summary, participants, consequences\n\n"
            "SCENE CONTENT:\n"
            "{scene_content}\n\n"
            "EXISTING COMPENDIUM (check for duplicates):\n"
            "{existing_compendium}\n\n"
            "OUTPUT FORMAT (JSON only, no commentary):\n"
            "{\n"
            "  \"categories\": [\n"
            "    {\n"
            "      \"name\": \"Characters|Locations|Objects|Factions|Events\",\n"
            "      \"entries\": [\n"
            "        {\n"
            "          \"name\": \"EntityName\",\n"
            "          \"content\": \"Concise description focusing on permanent traits\",\n"
            "          \"relationships\": [{\"name\": \"related_entry\", \"type\": \"relationship_type\"}], (optional)\n"
            "          \"metadata\": {\"introduced_in\": \"scene_name\", \"last_seen\": \"scene_name\"}\n"
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}"
        ),
    )

    prompt = analysis_template.format(
        scene_content=scene_content,
        existing_compendium=json.dumps(existing_compendium, indent=2),
        context=context,
    )

    try:
        success, response = analyze_scene_with_llm(prompt, overrides)
        if not success:
            return False, None, str(response)

        cleaned_response = preprocess_json_string(response)
        repaired_response = repair_incomplete_json(cleaned_response)
        if repaired_response is None:
            return False, None, "AI returned invalid JSON that could not be repaired"

        try:
            ai_compendium = json.loads(repaired_response)
            return True, ai_compendium, None
        except json.JSONDecodeError as jde:
            logger.exception("JSON decode error after repair: %s", jde)
            return False, None, "AI returned invalid JSON format"
    except Exception as e:
        logger.exception("analyze_scene failed: %s", e)
        return False, None, str(e)
