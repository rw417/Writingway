from muse.prompt_handler import _format_prompt_messages

messages = [
    {"role": "system", "content": "System instructions."},
    {"role": "user", "content": "User says something."},
    {"role": "assistant", "content": "Assistant replies."}
]

result = _format_prompt_messages(messages)
print(result)