from muse.prompt_handler import assemble_final_prompt

prompt_config = {
    "name": "T",
    "default": False,
    "provider": "OpenRouter",
    "model": "deepseek/deepseek-r1-0528",
    "max_tokens": 2000,
    "temperature": 0.7,
    "messages": [
        {"role": "system", "content": "This should be system. {pov}"},
        {"role": "user", "content": "Should be user"},
        {"role": "user", "content": "Should be assistant"},
        {"role": "assistant", "content": "User 2222"}
    ],
    "type": "prompt",
    "id": "6bb0a314-658d-4c85-bf4f-ce96e26a987a"
}

additional_vars = {'pov': 'third-person'}

user_input = "This is the user input."
current_scene_text = "This is the story so far."
extra_context = "This is extra context."

final_prompt = assemble_final_prompt(
    prompt_config,
    user_input,
    additional_vars=additional_vars,
    current_scene_text=current_scene_text,
    extra_context=extra_context
)

print("--- Final Prompt Output ---")
print(final_prompt)
