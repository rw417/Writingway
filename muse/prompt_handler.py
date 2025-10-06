# prompt_handler.py
import json
import os

from langchain.prompts import PromptTemplate
from settings.llm_api_aggregator import WWApiAggregator

DEFAULT_PROMPT_FALLBACK = "Write a story chapter based on the following user input"




def _format_prompt_messages(messages, variables=None):
    """Combine the content of all message dicts in order, substituting variables."""
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
        try:
            content = content.format(**variables)
        except Exception:
            pass  # If a variable is missing, leave as-is
        evaluated.append(content)
    return "\n\n".join(evaluated).strip()


try:
    _
except NameError:
    _ = lambda s: s


def assemble_final_prompt(prompt_config, user_input, additional_vars=None, current_scene_text=None, extra_context=None):
    """
    Build a chat-style messages list for chat-completion APIs.
    - prompt_config["messages"] entries are formatted with variables and kept in order.
    - extra_context, current_scene_text, user_input and additional_vars are appended as user messages.
    Returns: List[Dict[str, str]] where each dict has "role" and "content".
    """
    # Base messages from the prompt config, with variable substitution
    prompt_messages = prompt_config.get("messages") or []

    # Prepare variables for substitution
    variables = dict(additional_vars or {})
    variables.update({
        "user_input": user_input or "",
        "context": extra_context or "",
        "story_so_far": current_scene_text or ""
    })

    evaluated_messages = []
    for entry in prompt_messages:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role", "user")
        content = (entry.get("content", "") or "").strip()
        if not content:
            continue
        try:
            content = content.format(**variables)
        except Exception:
            # If formatting fails, keep raw content
            pass
        evaluated_messages.append({"role": role, "content": content})

    # # Append extra pieces as user messages (if present)
    # if extra_context:
    #     evaluated_messages.append({"role": "user", "content": extra_context})
    # if current_scene_text:
    #     evaluated_messages.append({"role": "user", "content": current_scene_text})
    # if additional_vars:
    #     # Represent additional_vars as a compact user message
    #     kv_lines = "\n".join(f"{k}: {v}" for k, v in (additional_vars.items()))
    #     if kv_lines:
    #         evaluated_messages.append({"role": "user", "content": kv_lines})
    # if user_input:
    #     evaluated_messages.append({"role": "user", "content": user_input})

    return evaluated_messages

def preview_final_prompt(prompt_config, user_input, additional_vars=None, current_scene_text=None, extra_context=None):
    """Generate a plain-text preview by concatenating the built messages' contents."""
    messages = assemble_final_prompt(prompt_config, user_input, additional_vars, current_scene_text, extra_context)
    # Preview shows combined content only (no role headings)
    return "\n\n".join(m.get("content", "") for m in messages).strip()

def send_final_prompt(final_prompt, prompt_config=None, overrides=None):
    """
    Sends the final prompt to the LLM using settings from the prompt's configuration.
    The configuration should include keys such as "provider", "model", "timeout", and "api_key".

    If no prompt_config is provided, then any overrides passed will be used as the configuration.
    If the resulting configuration is missing an API key (and the provider isn't "Local"), 
    the function will attempt to load the API key from settings.json based on the provider.

    Additional overrides (if provided) are merged afterward.
    Returns the generated text.
    """
    # If prompt_config is not provided, treat 'overrides' as the prompt configuration.
    if prompt_config is None:
        prompt_config = overrides.copy() if overrides else {}
        overrides = {}

    # Build the dictionary of overrides from the prompt configuration.
    prompt_overrides = {
        "provider": prompt_config.get("provider", "Local"),
        "model": prompt_config.get("model", "Local Model"),
    }
    # Merge any additional overrides if provided.
    if overrides:
        prompt_overrides.update(overrides)

    try:
        # Send the prompt to the LLM API aggregator.
        return WWApiAggregator.send_prompt_to_llm(final_prompt, overrides=prompt_overrides)
    except Exception as e:
        return(f"Error sending prompt to LLM: {e}")