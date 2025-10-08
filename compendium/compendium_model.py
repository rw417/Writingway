import os
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class CompendiumModel:
    """Simple model to manage compendium data and file I/O.

    Responsibilities:
    - load/save compendium JSON
    - normalize entry content (ensure content.description and uuid)
    - provide get/set helpers and apply AI compendium merges
    """

    def __init__(self, compendium_file: str):
        self.compendium_file = compendium_file
        self.compendium_data: Dict[str, Any] = {"categories": [], "extensions": {"entries": {}}}

    def load(self) -> None:
        if not os.path.exists(self.compendium_file):
            # create default structure
            self.compendium_data = {
                "categories": [
                    {
                        "name": "Characters",
                        "entries": [
                            {
                                "name": "Readme",
                                "content": {"description": "This is a dummy entry. You can view and edit extended data in this window."},
                                "uuid": str(uuid.uuid4()),
                            }
                        ],
                    }
                ],
                "extensions": {"entries": {}},
            }
            self.save()
            return
        with open(self.compendium_file, "r", encoding="utf-8") as f:
            self.compendium_data = json.load(f)
        # normalize
        self._ensure_structure()
        self._migrate_entries()

    def save(self) -> None:
        self._ensure_structure()
        dirpath = os.path.dirname(self.compendium_file)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath, exist_ok=True)
        with open(self.compendium_file, "w", encoding="utf-8") as f:
            json.dump(self.compendium_data, f, indent=2)

    def _ensure_structure(self) -> None:
        if "categories" not in self.compendium_data:
            self.compendium_data["categories"] = []
        if "extensions" not in self.compendium_data:
            self.compendium_data["extensions"] = {"entries": {}}
        elif "entries" not in self.compendium_data["extensions"]:
            self.compendium_data["extensions"]["entries"] = {}

    def _normalize_entry_content(self, entry: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        content = entry.get("content", "")
        changed = False
        if isinstance(content, dict):
            if "description" not in content:
                content["description"] = ""
                changed = True
            normalized = content
        elif isinstance(content, str):
            normalized = {"description": content}
            entry["content"] = normalized
            changed = True
        else:
            normalized = {"description": ""}
            entry["content"] = normalized
            changed = True
        return normalized, changed

    def normalize_entry_content(self, entry: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """Public wrapper so callers outside the model can reuse the normalization logic."""
        return self._normalize_entry_content(entry)

    def _migrate_entries(self) -> None:
        changed = False
        content_changed = False
        for cat in self.compendium_data.get("categories", []):
            for entry in cat.get("entries", []):
                if "uuid" not in entry:
                    entry["uuid"] = str(uuid.uuid4())
                    changed = True
                _, updated = self._normalize_entry_content(entry)
                if updated:
                    content_changed = True
        if changed or content_changed:
            self.save()

    # Public API helpers
    def get_categories(self) -> List[Dict[str, Any]]:
        return self.compendium_data.get("categories", [])

    def find_entry(self, entry_name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Return (category_name, entry_dict) if found, else None."""
        for cat in self.get_categories():
            for entry in cat.get("entries", []):
                if entry.get("name") == entry_name:
                    return cat.get("name"), entry
        return None

    def add_category(self, name: str) -> None:
        self._ensure_structure()
        self.compendium_data["categories"].append({"name": name, "entries": []})
        self.save()

    def add_entry(self, category_name: str, entry_payload: Dict[str, Any]) -> None:
        self._ensure_structure()
        for cat in self.compendium_data["categories"]:
            if cat.get("name") == category_name:
                entry = dict(entry_payload)
                if "uuid" not in entry:
                    entry["uuid"] = str(uuid.uuid4())
                if "content" not in entry:
                    entry["content"] = {"description": ""}
                cat["entries"].append(entry)
                self.save()
                return
        # category not found, create it
        self.compendium_data["categories"].append({"name": category_name, "entries": [entry_payload]})
        self.save()

    def delete_entry(self, entry_name: str) -> bool:
        for cat in self.compendium_data.get("categories", []):
            entries = cat.get("entries", [])
            for idx, entry in enumerate(entries):
                if entry.get("name") == entry_name:
                    entries.pop(idx)
                    # remove extensions too
                    self.compendium_data.get("extensions", {}).get("entries", {}).pop(entry_name, None)
                    self.save()
                    return True
        return False

    def as_data(self) -> Dict[str, Any]:
        return self.compendium_data

    def apply_ai_compendium(self, ai_compendium: Dict[str, Any]) -> None:
        """Merge AI-provided compendium into existing data.

        Strategy: for each AI category/entry, if category exists merge entries by name
        (replacing or adding), else append the category.
        """
        self._ensure_structure()
        existing = self.compendium_data
        existing_categories = {cat["name"]: cat for cat in existing.get("categories", [])}
        if not ai_compendium:
            return
        for new_cat in ai_compendium.get("categories", []):
            name = new_cat.get("name", "Unnamed Category")
            if name in existing_categories:
                existing_entries = {e.get("name"): e for e in existing_categories[name].get("entries", [])}
                for new_entry in new_cat.get("entries", []):
                    entry_name = new_entry.get("name")
                    normalized = dict(new_entry)
                    if "content" in normalized and isinstance(normalized["content"], str):
                        normalized["content"] = {"description": normalized["content"]}
                    if "uuid" not in normalized:
                        normalized["uuid"] = str(uuid.uuid4())
                    existing_entries[entry_name] = normalized
                    existing.setdefault("extensions", {}).setdefault("entries", {})[entry_name] = {
                        "relationships": new_entry.get("relationships", [])
                    }
                existing_categories[name]["entries"] = list(existing_entries.values())
            else:
                normalized_entries = []
                for entry in new_cat.get("entries", []):
                    e = dict(entry)
                    if "content" in e and isinstance(e["content"], str):
                        e["content"] = {"description": e["content"]}
                    if "uuid" not in e:
                        e["uuid"] = str(uuid.uuid4())
                    normalized_entries.append(e)
                    existing.setdefault("extensions", {}).setdefault("entries", {})[e.get("name")] = {
                        "relationships": entry.get("relationships", [])
                    }
                existing.setdefault("categories", []).append({"name": name, "entries": normalized_entries})
        self.save()
