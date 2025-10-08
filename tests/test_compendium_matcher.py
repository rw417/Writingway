import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from util.compendium_matcher import CompendiumMatcher, MatchRegistry, MatchSpan, TermInfo


class CompendiumMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.matcher = CompendiumMatcher()

    def test_matches_respect_word_boundaries(self):
        terms = [
            TermInfo(entry_name="Goblin", entry_uuid="1", category_name="Creatures", description="Sneaky creature", term="Goblin", source="name"),
            TermInfo(entry_name="Knight", entry_uuid="2", category_name="People", description="Armored warrior", term="Knight", source="name"),
        ]
        self.matcher.rebuild(terms)

        text = "The GoblinKing battled the Goblin alongside a Knight."
        matches = self.matcher.find_in_text(text)
        found_terms = [span.term_info.term for span in matches]

        self.assertIn("Goblin", found_terms)
        self.assertIn("Knight", found_terms)
        # Ensure partial matches like "GoblinKing" do not trigger
        goblin_positions = [span.start for span in matches if span.term_info.term == "Goblin"]
        self.assertEqual(len(goblin_positions), 1)
        self.assertEqual(text[goblin_positions[0]:goblin_positions[0] + len("Goblin")], "Goblin")

    def test_case_sensitive_matching(self):
        terms = [TermInfo(entry_name="Goblin", entry_uuid="1", category_name="Creatures", description="Sneaky creature", term="Goblin", source="name")]
        self.matcher.rebuild(terms)
        matches = self.matcher.find_in_text("the goblin watches")
        self.assertEqual(matches, [])

    def test_alias_terms_are_detected(self):
        terms = [
            TermInfo(entry_name="Goblin King", entry_uuid="1", category_name="Creatures", description="Leader of goblins", term="Goblin King", source="name"),
            TermInfo(entry_name="Goblin King", entry_uuid="1", category_name="Creatures", description="Leader of goblins", term="GK", source="alias"),
        ]
        self.matcher.rebuild(terms)
        text = "A GK appeared and the Goblin King fled."
        matches = self.matcher.find_in_text(text)
        found = {(span.term_info.term, span.start) for span in matches}
        self.assertIn(("GK", text.index("GK")), found)
        self.assertIn(("Goblin King", text.index("Goblin King")), found)


class MatchRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_update_block_and_serialization(self):
        registry = MatchRegistry()
        term = TermInfo(entry_name="Goblin", entry_uuid="1", category_name="Creatures", description="Sneaky creature", term="Goblin", source="name")
        span = MatchSpan(start=4, length=6, term_info=term)

        registry.update_block("doc", 0, 0, [span])
        serialized = registry.to_serializable()
        doc_entries = serialized["documents"].get("doc", [])
        self.assertEqual(len(doc_entries), 1)
        self.assertEqual(doc_entries[0]["term"], "Goblin")
        self.assertEqual(doc_entries[0]["start"], 4)

        # Removing matches should clear the document entry
        registry.update_block("doc", 0, 0, [])
        serialized_after = registry.to_serializable()
        self.assertNotIn("doc", serialized_after["documents"])


if __name__ == "__main__":
    unittest.main()
