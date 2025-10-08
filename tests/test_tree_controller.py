import os
import tempfile
import json

from PyQt5.QtWidgets import QTreeWidget, QApplication

from compendium.compendium_model import CompendiumModel
from compendium.tree_controller import TreeController


def test_tree_controller_populate_and_find(tmp_path):
    # prepare a simple compendium JSON file
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    comp_path = proj_dir / "compendium.json"
    data = {
        "categories": [
            {"name": "Cat1", "entries": [{"name": "E1", "content": {"description": "d1"}, "uuid": "u1"}]}
        ],
        "extensions": {"entries": {}}
    }
    comp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    model = CompendiumModel(str(comp_path))
    model.load()

    # ensure a QApplication exists for widget creation
    app = QApplication.instance() or QApplication([])

    tree = QTreeWidget()
    controller = TreeController(tree, model)
    controller.populate_tree()

    # verify top-level category exists and entry is present
    assert tree.topLevelItemCount() == 1
    cat_item = tree.topLevelItem(0)
    assert cat_item.text(0) == "Cat1"
    assert cat_item.childCount() == 1

    # find entry using controller
    item = controller.get_entry_item("E1")
    assert item is not None
    assert item.text(0) == "E1"
