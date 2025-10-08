import json
import pytest

from compendium import ai_integration

class DummyAggregator:
    @staticmethod
    def send_prompt_to_llm(prompt, overrides=None):
        # Return a fenced JSON string
        return '```json\n{"categories": [{"name": "Characters", "entries": [{"name": "Bob", "content": "Tall man."}]}]}\n```'


def test_analyze_scene_success(monkeypatch):
    monkeypatch.setattr(ai_integration, 'WWApiAggregator', DummyAggregator)
    scene = "Bob entered the room. He is tall."
    existing = {"categories": []}
    overrides = {}
    success, compendium, err = ai_integration.analyze_scene(scene, existing, overrides, context={})
    assert success is True
    assert err is None
    assert isinstance(compendium, dict)
    assert 'categories' in compendium
    assert compendium['categories'][0]['name'] == 'Characters'


def test_analyze_scene_invalid_json(monkeypatch):
    class BadAggregator:
        @staticmethod
        def send_prompt_to_llm(prompt, overrides=None):
            # Return badly truncated JSON that cannot be repaired
            return '```json\n{"categories": [ {"name": "Characters", "entries": [ {"name": "Bob" '  

    monkeypatch.setattr(ai_integration, 'WWApiAggregator', BadAggregator)
    scene = "Truncated"
    existing = {"categories": []}
    overrides = {}
    success, compendium, err = ai_integration.analyze_scene(scene, existing, overrides, context={})
    assert success is False
    assert compendium is None
    assert err is not None
