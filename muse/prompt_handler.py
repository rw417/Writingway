# prompt_handler.py
import json
import os

from langchain.prompts import PromptTemplate
from settings.llm_api_aggregator import WWApiAggregator
from .prompt_variables import get_prompt_variables, set_user_input, evaluate_variable_expression
from .jinja_renderer import render_template

DEFAULT_PROMPT_FALLBACK = "Write a story chapter based on the following user input"

# gettext '_' fallback for static analysis / standalone edits
if '_' not in globals():
    _ = lambda s: s


def _format_prompt_messages(messages, variables=None):
    """
    Combine the content of all message dicts in order, substituting variables safely.
    Uses safe variable formatting that handles missing variables individually.
    """
    if not isinstance(messages, list):
        return ""
    variables = variables or {}
    evaluated = []
    for entry in messages:
        if not isinstance(entry, dict):
            continue
        content = (entry.get("content", "").strip())
        if not content:
            continue
        # Use safe variable formatting
        content = _safe_format_variables(content, variables)
        evaluated.append(content)
    return "\n\n".join(evaluated).strip()


def _safe_format_variables(content, variables):
    """Render a single message content with Jinja2, preserving legacy {var} syntax.

    This uses the centralized Jinja renderer which converts single-brace
    placeholders to Jinja2 and renders with provided variables and helpers.
    """
    return render_template(content or "", variables)


if '_' not in globals():
    _ = lambda s: s


def assemble_final_prompt(prompt_config, user_input, additional_vars=None, current_scene_text=None, extra_context=None):
    """
    Build a chat-style messages list for chat-completion APIs.
    Uses the centralized variable system to collect all available variables.
    Returns: List[Dict[str, str]] where each dict has "role" and "content".
    """
    # Set user input in variable manager
    set_user_input(user_input)
    
    # Get all variables from the centralized system
    variables = get_prompt_variables()
    
    # Legacy compatibility - merge any additional_vars, current_scene_text, extra_context
    if additional_vars:
        variables.update(additional_vars)
    if current_scene_text:
        variables['story_so_far'] = current_scene_text
    if extra_context:
        variables['context'] = extra_context
    if user_input:
        variables['user_input'] = user_input

    # Base messages from the prompt config, with variable substitution
    prompt_messages = prompt_config.get("messages") or []
    evaluated_messages = []
    
    for entry in prompt_messages:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role", "user")
        content = (entry.get("content", "") or "").strip()
        if not content:
            continue
        
        # Handle variable substitution with individual error handling
        formatted_content = _safe_format_variables(content, variables)
        evaluated_messages.append({"role": role, "content": formatted_content})

    return evaluated_messages

# def preview_final_prompt(prompt_config, user_input, additional_vars=None, current_scene_text=None, extra_context=None):
#     """Generate a plain-text preview by concatenating the built messages' contents."""
#     messages = assemble_final_prompt(prompt_config, user_input, additional_vars, current_scene_text, extra_context)
#     # Preview shows combined content only (no role headings)
#     return "\n\n".join(m.get("content", "") for m in messages).strip()

# def send_final_prompt(final_prompt, prompt_config=None, overrides=None):
#     """
#     Sends the final prompt to the LLM using settings from the prompt's configuration.
#     The configuration should include keys such as "provider", "model", "timeout", and "api_key".

#     If no prompt_config is provided, then any overrides passed will be used as the configuration.
#     If the resulting configuration is missing an API key (and the provider isn't "Local"), 
#     the function will attempt to load the API key from settings.json based on the provider.

#     Additional overrides (if provided) are merged afterward.
#     Returns the generated text.
#     """
#     # If prompt_config is not provided, treat 'overrides' as the prompt configuration.
#     if prompt_config is None:
#         prompt_config = overrides.copy() if overrides else {}
#         overrides = {}

#     # Build the dictionary of overrides from the prompt configuration.
#     prompt_overrides = {
#         "provider": prompt_config.get("provider", "Local"),
#         "model": prompt_config.get("model", "Local Model"),
#     }
#     # Merge any additional overrides if provided.
#     if overrides:
#         prompt_overrides.update(overrides)

#     try:
#         # Send the prompt to the LLM API aggregator.
#         return WWApiAggregator.send_prompt_to_llm(final_prompt, overrides=prompt_overrides)
#     except Exception as e:
#         return(f"Error sending prompt to LLM: {e}")