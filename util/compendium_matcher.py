from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PyQt5.QtCore import QObject, pyqtSignal, QFileSystemWatcher, QTimer
from PyQt5.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from compendium.compendium_manager import CompendiumManager


@dataclass(frozen=True)
class TermInfo:
    """Metadata describing a term that can be matched in text."""

    entry_name: str
    entry_uuid: str
    term: str
    source: str  # "name" or "alias"


@dataclass(frozen=True)
class MatchSpan:
    """A single match found within a block of text."""

    start: int
    length: int
    term_info: TermInfo


class _TrieNode:
    __slots__ = ("children", "outputs")

    def __init__(self) -> None:
        self.children: Dict[str, "_TrieNode"] = {}
        self.outputs: List[TermInfo] = []


class CompendiumMatcher:
    """Efficiently scans text for compendium terms respecting whole-word boundaries."""

    def __init__(self) -> None:
        self._root = _TrieNode()
        self._term_count = 0

    def rebuild(self, terms: Sequence[TermInfo]) -> None:
        """Reconstruct the internal trie from the provided term list."""

        self._root = _TrieNode()
        self._term_count = 0
        for info in terms:
            if not info.term:
                continue
            node = self._root
            for ch in info.term:
                node = node.children.setdefault(ch, _TrieNode())
            node.outputs.append(info)
            self._term_count += 1

    @staticmethod
    def _is_word_char(ch: str) -> bool:
        return ch.isalnum() or ch == "_"

    def _is_word_boundary(self, text: str, start: int, end: int) -> bool:
        before = text[start - 1] if start > 0 else None
        after = text[end] if end < len(text) else None
        is_start_boundary = before is None or not self._is_word_char(before)
        is_end_boundary = after is None or not self._is_word_char(after)
        return is_start_boundary and is_end_boundary

    def find_in_text(self, text: str) -> List[MatchSpan]:
        if not text or self._term_count == 0:
            return []

        results: List[MatchSpan] = []
        text_length = len(text)
        for start in range(text_length):
            node = self._root.children.get(text[start])
            if not node:
                continue
            end = start + 1
            current = node
            while True:
                if current.outputs and self._is_word_boundary(text, start, end):
                    for info in current.outputs:
                        results.append(MatchSpan(start=start, length=end - start, term_info=info))
                if end >= text_length:
                    break
                next_char = text[end]
                current = current.children.get(next_char)
                if current is None:
                    break
                end += 1
        return results


class MatchRegistry(QObject):
    """Stores match locations for multiple documents and emits updates when they change."""

    matches_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._documents: Dict[str, Dict[int, List[Dict]]] = {}

    def clear_all(self) -> None:
        self._documents.clear()

    def clear_document(self, document_id: str) -> None:
        if document_id in self._documents:
            del self._documents[document_id]
            self.matches_changed.emit(document_id)

    def update_block(
        self,
        document_id: str,
        block_number: int,
        block_position: int,
        matches: Sequence[MatchSpan],
    ) -> None:
        doc_blocks = self._documents.setdefault(document_id, {})
        new_entries = [
            {
                "entry_name": span.term_info.entry_name,
                "entry_uuid": span.term_info.entry_uuid,
                "term": span.term_info.term,
                "source": span.term_info.source,
                "block": block_number,
                "start": block_position + span.start,
                "length": span.length,
            }
            for span in matches
        ]

        current_entries = doc_blocks.get(block_number)
        if current_entries == new_entries:
            return

        if new_entries:
            doc_blocks[block_number] = new_entries
        else:
            doc_blocks.pop(block_number, None)
            if not doc_blocks:
                self._documents.pop(document_id, None)

        self.matches_changed.emit(document_id)

    def iter_document_matches(self, document_id: str) -> Iterable[Dict]:
        doc_blocks = self._documents.get(document_id, {})
        for block_number in sorted(doc_blocks.keys()):
            for entry in sorted(doc_blocks[block_number], key=lambda item: item["start"]):
                yield entry

    def to_serializable(self) -> Dict:
        return {
            "documents": {
                doc_id: [entry for entry in self.iter_document_matches(doc_id)]
                for doc_id in self._documents.keys()
            }
        }

    def load_serialized(self, payload: Optional[Dict]) -> None:
        self._documents.clear()
        if not payload:
            return
        documents = payload.get("documents", {})
        for doc_id, entries in documents.items():
            block_map: Dict[int, List[Dict]] = {}
            for entry in entries:
                block = int(entry.get("block", 0))
                block_map.setdefault(block, []).append(dict(entry))
            for block_entries in block_map.values():
                block_entries.sort(key=lambda item: item.get("start", 0))
            self._documents[doc_id] = block_map

    def document_ids(self) -> List[str]:
        return list(self._documents.keys())


class TrackedMatchHighlighter(QSyntaxHighlighter):
    """Underline compendium matches and push locations into the registry."""

    def __init__(
        self,
        document: QTextDocument,
        matcher: Optional[CompendiumMatcher],
        registry: MatchRegistry,
        document_id: str,
        underline_color: Optional[QColor] = None,
    ) -> None:
        super().__init__(document)
        self._matcher = matcher
        self._registry = registry
        self._document_id = document_id
        self._format = QTextCharFormat()
        self._format.setFontUnderline(True)
        self._format.setUnderlineStyle(QTextCharFormat.SingleUnderline)
        if underline_color:
            self._format.setUnderlineColor(underline_color)

    def set_matcher(self, matcher: Optional[CompendiumMatcher]) -> None:
        self._matcher = matcher
        self.rehighlight()

    def document_id(self) -> str:
        return self._document_id

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        block = self.currentBlock()
        if not self._matcher:
            self._registry.update_block(self._document_id, block.blockNumber(), block.position(), [])
            return

        matches = self._matcher.find_in_text(text)
        for span in matches:
            self.setFormat(span.start, span.length, self._format)

        self._registry.update_block(
            self._document_id,
            block.blockNumber(),
            block.position(),
            matches,
        )


class CompendiumMatchService(QObject):
    """Coordinates term loading, highlighting, and persistence for a project."""

    matcher_reloaded = pyqtSignal()

    def __init__(self, project_name: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.project_name = project_name
        self._manager = CompendiumManager(project_name)
        self._matcher = CompendiumMatcher()
        self.registry = MatchRegistry(self)
        self._highlighters: List[TrackedMatchHighlighter] = []
        self._matches_filename = "compendium_matches.json"
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.fileChanged.connect(self._on_compendium_fs_event)
        self._fs_watcher.directoryChanged.connect(self._on_compendium_fs_event)
        self._fs_refresh_timer = QTimer(self)
        self._fs_refresh_timer.setSingleShot(True)
        self._fs_refresh_timer.setInterval(250)
        self._fs_refresh_timer.timeout.connect(self.refresh_terms)
        self.refresh_terms()
        self._reset_watcher_paths()
        self._load_persisted_matches()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def refresh_terms(self) -> None:
        data = self._manager.load_data()
        terms = self._extract_terms(data)
        self._matcher.rebuild(terms)
        for highlighter in self._highlighters:
            highlighter.set_matcher(self._matcher)
        self.matcher_reloaded.emit()
        self._reset_watcher_paths()

    def attach_highlighter(self, document: QTextDocument, document_id: str, underline_color: Optional[QColor] = None) -> TrackedMatchHighlighter:
        highlighter = TrackedMatchHighlighter(document, self._matcher, self.registry, document_id, underline_color)
        self._highlighters.append(highlighter)
        return highlighter

    def detach_highlighter(self, highlighter: TrackedMatchHighlighter) -> None:
        if highlighter in self._highlighters:
            self._highlighters.remove(highlighter)
            self.registry.clear_document(highlighter.document_id())

    def save_matches(self) -> None:
        project_dir = os.path.dirname(self._manager.get_filepath())
        if not project_dir:
            return
        os.makedirs(project_dir, exist_ok=True)
        payload = self.registry.to_serializable()
        target_path = os.path.join(project_dir, self._matches_filename)
        try:
            with open(target_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Failed to save compendium matches: {exc}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_persisted_matches(self) -> None:
        project_dir = os.path.dirname(self._manager.get_filepath())
        matches_path = os.path.join(project_dir, self._matches_filename)
        if not os.path.exists(matches_path):
            return
        try:
            with open(matches_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.registry.load_serialized(payload)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Failed to load compendium matches: {exc}")

    def _reset_watcher_paths(self) -> None:
        watcher = getattr(self, "_fs_watcher", None)
        if watcher is None:
            return
        watcher.blockSignals(True)
        for path in list(watcher.files()):
            watcher.removePath(path)
        for path in list(watcher.directories()):
            watcher.removePath(path)
        watcher.blockSignals(False)

        compendium_path = self._manager.get_filepath()
        compendium_dir = os.path.dirname(compendium_path)
        if os.path.isdir(compendium_dir):
            watcher.addPath(compendium_dir)
        if os.path.exists(compendium_path):
            watcher.addPath(compendium_path)

    def _on_compendium_fs_event(self, _path: str) -> None:
        self._reset_watcher_paths()
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        timer = getattr(self, "_fs_refresh_timer", None)
        if timer is None:
            return
        if timer.isActive():
            timer.stop()
        timer.start()

    def _extract_terms(self, data: Dict) -> List[TermInfo]:
        terms: List[TermInfo] = []
        seen_entries: Dict[Tuple[str, str], bool] = {}
        categories = data.get("categories", []) or []
        extensions_entries = data.get("extensions", {}).get("entries", {}) if data else {}

        for category in categories:
            for entry in category.get("entries", []) or []:
                entry_name = (entry.get("name") or "").strip()
                if not entry_name:
                    continue
                entry_uuid = entry.get("uuid", "")
                extended = extensions_entries.get(entry_name, {})
                track = extended.get("track_by_name", True)
                if not track:
                    continue

                self._append_term(terms, seen_entries, entry_name, entry_uuid, entry_name, "name")
                for alias in self._normalize_aliases(extended.get("aliases")):
                    if alias:
                        self._append_term(terms, seen_entries, entry_name, entry_uuid, alias, "alias")
        return terms

    def _append_term(
        self,
        terms: List[TermInfo],
        seen_entries: Dict[Tuple[str, str], bool],
        entry_name: str,
        entry_uuid: str,
        term: str,
        source: str,
    ) -> None:
        key = (entry_uuid or entry_name, term)
        if key in seen_entries:
            return
        seen_entries[key] = True
        terms.append(TermInfo(entry_name=entry_name, entry_uuid=entry_uuid or entry_name, term=term, source=source))

    @staticmethod
    def _normalize_aliases(raw_aliases: Optional[object]) -> List[str]:
        if raw_aliases is None:
            return []
        if isinstance(raw_aliases, str):
            candidates = raw_aliases.split(",")
        elif isinstance(raw_aliases, (list, tuple)):
            candidates = raw_aliases
        else:
            candidates = []
        normalized: List[str] = []
        for alias in candidates:
            if not isinstance(alias, str):
                continue
            cleaned = alias.strip()
            if cleaned:
                normalized.append(cleaned)
        return normalized