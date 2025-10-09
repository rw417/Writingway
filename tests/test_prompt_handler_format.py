import unittest
from muse.prompt_handler import _format_prompt_messages

class TestFormatPromptMessages(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(_format_prompt_messages([]), "")

    def test_non_list(self):
        self.assertEqual(_format_prompt_messages(None), "")
        self.assertEqual(_format_prompt_messages("notalist"), "")

    def test_single_system_message(self):
        messages = [{"role": "system", "content": "System message."}]
        expected = "### System\nSystem message."
        self.assertEqual(_format_prompt_messages(messages), expected)

    def test_multiple_roles(self):
        messages = [
            {"role": "system", "content": "System message."},
            {"role": "user", "content": "User message."},
            {"role": "assistant", "content": "Assistant message."}
        ]
        expected = (
            "### System\nSystem message.\n\n"
            "### User\nUser message.\n\n"
            "### Assistant\nAssistant message."
        )
        self.assertEqual(_format_prompt_messages(messages), expected)

    def test_ignores_empty_content(self):
        messages = [
            {"role": "system", "content": ""},
            {"role": "user", "content": "  "},
            {"role": "assistant", "content": "Assistant message."}
        ]
        expected = "### Assistant\nAssistant message."
        self.assertEqual(_format_prompt_messages(messages), expected)

    def test_missing_role_defaults_to_system(self):
        messages = [
            {"content": "No role message."}
        ]
        expected = "### System\nNo role message."
        self.assertEqual(_format_prompt_messages(messages), expected)

    def test_non_dict_entries_ignored(self):
        messages = [
            {"role": "system", "content": "System message."},
            "notadict",
            123,
            None
        ]
        expected = "### System\nSystem message."
        self.assertEqual(_format_prompt_messages(messages), expected)

if __name__ == "__main__":
    unittest.main()
