import os
import json
import tempfile
import shutil

from compendium.compendium_model import CompendiumModel


def test_compendium_model_load_save(tmp_path):
    # create a temp project dir
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    comp_path = proj_dir / "compendium.json"

    model = CompendiumModel(str(comp_path))

    # initially save default
    model.save()
    assert os.path.exists(str(comp_path))

    # add category and entry
    model.add_category("TestCat")
    model.add_entry("TestCat", {"name": "Entry1", "content": {"description": "desc"}, "uuid": "u1"})
    model.save()

    # reload into new model instance and verify
    m2 = CompendiumModel(str(comp_path))
    m2.load()
    data = m2.as_data()
    cats = {c.get("name"): c for c in data.get("categories", [])}
    assert "TestCat" in cats
    entries = {e.get("name"): e for e in cats["TestCat"].get("entries", [])}
    assert "Entry1" in entries
