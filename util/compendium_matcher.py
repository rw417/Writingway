from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PyQt5.QtCore import QObject, pyqtSignal, QFileSystemWatcher, QTimer, Qt, QPoint, QEvent
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
    QTextLayout,
    QFontMetrics,
)
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

try:
    import sip  # type: ignore[import]
except ImportError:  # pragma: no cover - sip may not be available in headless tests
    sip = None  # type: ignore[assignment]

from compendium.compendium_manager import CompendiumManager
from util.cursor_manager import set_dynamic_clickable
from settings.theme_manager import ThemeManager


@dataclass(frozen=True)
class TermInfo:
    """Metadata describing a term that can be matched in text."""

    entry_name: str
    entry_uuid: str
    category_name: str
    description: str
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
                "category_name": span.term_info.category_name,
                "description": span.term_info.description,
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

    def find_match_at(self, document_id: str, position: int) -> Optional[Dict]:
        doc_blocks = self._documents.get(document_id)
        if not doc_blocks:
            return None
        for block_entries in doc_blocks.values():
            for entry in block_entries:
                start = entry.get("start", 0)
                length = entry.get("length", 0)
                if start <= position < start + length:
                    return entry
        return None


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
        self._format.setUnderlineStyle(QTextCharFormat.DashUnderline)
        if underline_color:
            self._format.setUnderlineColor(underline_color)
        # Hovered match state (absolute document positions)
        self._hover_start: Optional[int] = None
        self._hover_length: Optional[int] = None

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

        # If a hovered range overlaps this block, apply a background shade
        if self._hover_start is not None and self._hover_length is not None:
            block_start = block.position()
            block_end = block_start + len(text)
            hover_start = self._hover_start
            hover_end = self._hover_start + self._hover_length
            # Compute overlap
            overlap_start = max(block_start, hover_start)
            overlap_end = min(block_end, hover_end)
            if overlap_start < overlap_end:
                local_start = overlap_start - block_start
                local_len = overlap_end - overlap_start
                try:
                    color = ThemeManager.get_toggle_highlight_color(None)
                    # Preserve underline and other match styling while adding
                    # a background for hover. Start from the existing match
                    # format so underline remains visible.
                    hover_fmt = QTextCharFormat(self._format)
                    hover_fmt.setBackground(color)
                    self.setFormat(local_start, local_len, hover_fmt)
                except Exception:
                    # Defensive: don't fail highlighting if theme manager unavailable
                    pass

        self._registry.update_block(
            self._document_id,
            block.blockNumber(),
            block.position(),
            matches,
        )

    def set_hovered_range(self, start: Optional[int], length: Optional[int]) -> None:
        """Set the hovered absolute range (document positions). Passing None clears hover."""
        if start == self._hover_start and length == self._hover_length:
            return
        self._hover_start = start
        self._hover_length = length
        # Repaint to apply/remove hover background
        try:
            self.rehighlight()
        except Exception:
            pass


class MatchDetailsPopup(QWidget):
    """Popup widget showing compendium match information."""

    entry_activated = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.StrongFocus)
        self._entry_name: Optional[str] = None
        self._entry_uuid: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)

        self._category_label = QLabel()
        cat_font = self._category_label.font()
        cat_font.setPointSize(max(cat_font.pointSize() - 2, 8))
        self._category_label.setFont(cat_font)
        self._category_label.setStyleSheet("color: #666; text-transform: uppercase;")

        self._name_label = QLabel()
        name_font = self._name_label.font()
        name_font.setPointSize(name_font.pointSize() + 4)
        name_font.setBold(True)
        self._name_label.setFont(name_font)

        self._description_label = QLabel()
        self._description_label.setWordWrap(True)
        self._description_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(self._category_label)
        layout.addWidget(self._name_label)
        # Allow the description label to wrap and expand horizontally.
        self._description_label.setWordWrap(True)
        layout.addWidget(self._description_label)

        # Keep a reference to the layout for sizing calculations used when eliding text.
        self._layout = layout

        # Enforce a fixed width and a maximum height for the popup as requested.
        # Fixed width: 350 px. Max height: 250 px.
        try:
            self.setFixedWidth(350)
            self.setMaximumHeight(250)
        except Exception:
            # Defensive - some test environments may not support these calls.
            pass

        # Store the full description so we can compute an elided version when needed.
        self._full_description_text: Optional[str] = None

        # Ensure the popup and its child widgets show the pointing-hand cursor
        # while hovered, matching their clickable behavior.
        for widget in (self, self._category_label, self._name_label, self._description_label):
            if hasattr(widget, "setAttribute"):
                widget.setAttribute(Qt.WA_Hover, True)
            widget.setProperty("wwForceHandCursor", True)

    def set_entry_details(self, category: str, name: str, description: str, entry_uuid: str) -> None:
        self._category_label.setText(category.strip() or "")
        self._name_label.setText(name.strip() or "")
        self._full_description_text = ((description or "").strip() or "No description available.")
        # Update visible (possibly elided) description now that we have content.
        self._update_description_elided()
        self._entry_name = name
        self._entry_uuid = entry_uuid
        self.adjustSize()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            is_inside = self.rect().contains(event.pos())
            if is_inside and self._entry_name:
                self.entry_activated.emit(self._entry_name, self._entry_uuid or "")
                self.close()
                return
            if not is_inside:
                event.ignore()
                self.close()
                return
        super().mousePressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        event.ignore()

    def resizeEvent(self, event) -> None:  # noqa: N802 - update elided text when resized
        # Recompute the elided description when the popup size changes.
        try:
            self._update_description_elided()
        except Exception:
            pass
        super().resizeEvent(event)

    def _update_description_elided(self) -> None:
        """Compute a multi-line elided version of the full description so it fits
        within the popup's available area (respecting fixed width and max height).
        """
        if not hasattr(self, "_full_description_text") or self._full_description_text is None:
            return
        text = self._full_description_text

        # Determine available width inside the layout (account for left/right margins).
        try:
            left = self._layout.contentsMargins().left()
            right = self._layout.contentsMargins().right()
            available_width = max(10, self.width() - left - right)
        except Exception:
            available_width = max(10, self.width() - 24)

        # Determine available height for the description portion by subtracting
        # the heights of the other widgets and layout margins/spacings from the
        # popup's maximum height (we cap to the popup max height to avoid very
        # tall popups).
        try:
            max_height = min(self.maximumHeight(), 550)
            top = self._layout.contentsMargins().top()
            bottom = self._layout.contentsMargins().bottom()
            spacing = self._layout.spacing()
            cat_h = self._category_label.sizeHint().height()
            name_h = self._name_label.sizeHint().height()
            consumed = top + cat_h + spacing + name_h + spacing + bottom
            available_height = max(10, max_height - consumed)
        except Exception:
            available_height = max(10, 550 -  (self._category_label.sizeHint().height() + self._name_label.sizeHint().height()))

        font = self._description_label.font()
        fm = QFontMetrics(font)
        line_height = fm.lineSpacing() or fm.height() or 14
        max_lines = max(1, int(available_height // line_height))

        # Use QTextLayout to determine how the text would be broken into lines
        # for the given font and available width.
        tl = QTextLayout(text, font)
        tl.beginLayout()
        lines = []
        while True:
            line = tl.createLine()
            if not line.isValid():
                break
            line.setLineWidth(available_width)
            lines.append((line.textStart(), line.textLength()))
        tl.endLayout()

        # If text fits within available lines, show it raw; otherwise elide the
        # last visible line and assemble the visible portion.
        if len(lines) <= max_lines:
            self._description_label.setText(text)
            return

        visible = lines[:max_lines]
        parts: List[str] = []
        for start, length in visible[:-1]:
            parts.append(text[start : start + length])

        # Last visible line: prefer removing whole trailing words until '...' fits.
        last_start, last_length = visible[-1]
        last_sub = text[last_start : last_start + last_length]

        # Helper to produce a candidate with trailing whole-word removal.
        def elide_by_words(s: str) -> str:
            # If it already fits, return as-is
            if fm.width(s) <= available_width:
                return s
            words = s.rstrip().split()
            if not words:
                # fallback to mid-word elide
                return fm.elidedText(s, Qt.ElideRight, available_width)
            # Iteratively remove trailing words and test with appended ellipsis
            for cut in range(len(words), 0, -1):
                candidate = " ".join(words[:cut])
                candidate_with_dots = candidate.rstrip() + "..."
                if fm.width(candidate_with_dots) <= available_width:
                    return candidate_with_dots
            # If no whole-word truncation works, fallback to mid-word elide of original
            return fm.elidedText(s, Qt.ElideRight, available_width)

        elided_last = elide_by_words(last_sub)
        parts.append(elided_last)

        # Join with newline to preserve line breaks as laid out
        final = "\n".join(parts)
        self._description_label.setText(final)


class MatchClickController(QObject):
    """Installs handlers on a text widget to show match detail popups."""

    def __init__(
        self,
        text_widget: QWidget,
        document_id: str,
        registry: MatchRegistry,
        service: "CompendiumMatchService",
    ) -> None:
        super().__init__(text_widget)
        self._widget = text_widget
        self._document_id = document_id
        self._registry = registry
        self._service = service
        self._popup: Optional[MatchDetailsPopup] = None
        self._app = QApplication.instance()
        self._global_filter_active = False
        self._pressed_match_start: Optional[int] = None
        self._pressed_match_length: Optional[int] = None
        self._pressed_match_entry: Optional[Dict] = None
        self._hover_clickable: bool = False

        viewport = getattr(self._widget, "viewport", lambda: self._widget)()
        viewport.installEventFilter(self)
        self._viewport = viewport
        if hasattr(viewport, "setAttribute"):
            viewport.setAttribute(Qt.WA_Hover, True)
        if hasattr(viewport, "setMouseTracking"):
            viewport.setMouseTracking(True)
        self._widget.destroyed.connect(self._on_widget_destroyed)
        self._registry.matches_changed.connect(self._on_matches_changed)

    def shutdown(self) -> None:
        self._close_popup()
        if hasattr(self, "_viewport") and self._viewport:
            self._viewport.removeEventFilter(self)
            set_dynamic_clickable(self._viewport, False)
        try:
            self._registry.matches_changed.disconnect(self._on_matches_changed)
        except (TypeError, RuntimeError):
            pass
        if self._global_filter_active and self._app:
            with suppress(RuntimeError, TypeError):
                self._app.removeEventFilter(self)
            self._global_filter_active = False
        self.deleteLater()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        # Universal early check: if a mouse press occurred anywhere and a
        # popup is shown, close the popup when the press is outside the
        # popup geometry. Use event.globalPos() when available; otherwise
        # try to map local coordinates to global as a fallback.
        try:
            etype_early = event.type()
        except Exception:
            etype_early = None
        if self._popup and etype_early == QEvent.MouseButtonPress:
            gp = None
            gp_getter = getattr(event, "globalPos", None)
            if callable(gp_getter):
                try:
                    gp = gp_getter()
                except Exception:
                    gp = None
            if gp is None:
                # attempt to map local pos to global if possible
                pos_getter = getattr(event, "pos", None)
                if callable(pos_getter) and hasattr(obj, "mapToGlobal"):
                    try:
                        local = pos_getter()
                        gp = obj.mapToGlobal(local)
                    except Exception:
                        gp = None
            if gp is None:
                # fallback to cursor position
                try:
                    gp = QCursor.pos()
                except Exception:
                    gp = None
            if gp is not None:
                try:
                    if not self._popup.geometry().contains(gp):
                        self._close_popup()
                except Exception:
                    pass

        if obj is self._viewport:
            etype = event.type()
            if etype == QEvent.MouseButtonPress:
                button = getattr(event, "button", lambda: None)()
                if button == Qt.LeftButton:
                    self._capture_pressed_match(event.pos())
                else:
                    self._reset_pressed_match()
                if self._popup:
                    global_pos = self._viewport.mapToGlobal(getattr(event, "pos", lambda: QPoint())())
                    if not self._popup.geometry().contains(global_pos):
                        self._close_popup(reset_pressed=False)
            elif etype == QEvent.MouseButtonRelease and getattr(event, "button", lambda: None)() == Qt.LeftButton:
                self._handle_click(event.pos())
            elif etype in (QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
                self._update_hover_clickable(getattr(event, "pos", lambda: QPoint())())
            elif etype == QEvent.HoverLeave:
                self._update_hover_clickable(None)
        elif obj is self._app:
            etype = event.type()
            if etype in (QEvent.MouseMove, QEvent.HoverMove):
                global_pos_getter = getattr(event, "globalPos", None)
                if callable(global_pos_getter):
                    global_pos = global_pos_getter()
                else:
                    global_pos = QCursor.pos()
                self._update_hover_from_global(global_pos)
            if self._popup and etype == QEvent.MouseButtonPress:
                target_widget = getattr(event, "widget", lambda: None)()
                if target_widget and (target_widget is self._popup or self._popup.isAncestorOf(target_widget)):
                    return False
                global_pos = getattr(event, "globalPos", lambda: QPoint())()
                if self._popup.geometry().contains(global_pos):
                    return False
                self._close_popup()
                self._reset_pressed_match()
        return super().eventFilter(obj, event)

    def _handle_click(self, pos) -> None:
        match = self._match_at_position(pos)
        release_position = self._position_at(pos)
        pressed_start = self._pressed_match_start
        pressed_length = self._pressed_match_length
        pressed_entry = self._pressed_match_entry
        should_show = False
        popup_entry: Optional[Dict] = None

        if (
            match
            and pressed_start is not None
            and pressed_length is not None
            and match.get("start") == pressed_start
            and match.get("length") == pressed_length
        ):
            should_show = True
            popup_entry = match
        elif (
            not match
            and pressed_entry
            and pressed_start is not None
            and pressed_length is not None
            and release_position is not None
            and pressed_start <= release_position <= pressed_start + pressed_length
        ):
            should_show = True
            popup_entry = pressed_entry

        self._reset_pressed_match()
        if should_show and popup_entry is not None:
            self._show_popup(popup_entry, pos)
        else:
            self._close_popup()

    def _show_popup(self, match: Dict, click_pos) -> None:
        self._close_popup()
        popup = MatchDetailsPopup(self._widget)
        popup.set_entry_details(
            match.get("category_name", ""),
            match.get("entry_name", ""),
            match.get("description", ""),
            match.get("entry_uuid", ""),
        )
        popup.entry_activated.connect(self._service.handle_entry_activation)
        popup.destroyed.connect(self._on_popup_destroyed)
        self._popup = popup
        global_pos = self._viewport.mapToGlobal(click_pos)
        offset = QPoint(0, self._widget.fontMetrics().height())
        target_pos = global_pos + offset

        # Ensure the popup will be fully visible on screen. If it would be
        # cropped (e.g., too low), move it up or left as needed.
        try:
            screen = QApplication.screenAt(target_pos) or QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                popup_size = popup.sizeHint()
                px = target_pos.x()
                py = target_pos.y()
                # If right edge would be off-screen, shift left.
                if px + popup_size.width() > geo.right():
                    px = max(geo.left(), geo.right() - popup_size.width())
                # Use a 30px safety margin above the true bottom so the popup
                # doesn't appear too low. If bottom would be off-screen (past
                # geo.bottom() - 30), shift up.
                bottom_limit = geo.bottom() - 30
                if py + popup_size.height() > bottom_limit:
                    py = max(geo.top(), bottom_limit - popup_size.height())
                target_pos = QPoint(px, py)
        except Exception:
            # Defensive fallback: do nothing if screen info isn't available.
            pass

        popup.move(target_pos)
        popup.show()
        popup.raise_()
        popup.activateWindow()
        if self._app and not self._global_filter_active:
            self._app.installEventFilter(self)
            self._global_filter_active = True

    def _capture_pressed_match(self, pos: Optional[QPoint]) -> None:
        match = self._match_at_position(pos)
        if not match:
            self._reset_pressed_match()
            return
        self._pressed_match_start = match.get("start")
        self._pressed_match_length = match.get("length")
        self._pressed_match_entry = match

    def _reset_pressed_match(self) -> None:
        self._pressed_match_start = None
        self._pressed_match_length = None
        self._pressed_match_entry = None

    def _cursor_for_pos(self, pos: Optional[QPoint]):
        if pos is None or not hasattr(self._widget, "cursorForPosition"):
            return None
        return self._widget.cursorForPosition(pos)

    def _match_at_position(self, pos: Optional[QPoint]) -> Optional[Dict]:
        cursor = self._cursor_for_pos(pos)
        if not cursor:
            return None
        position = cursor.position()
        return self._registry.find_match_at(self._document_id, position)

    def _position_at(self, pos: Optional[QPoint]) -> Optional[int]:
        cursor = self._cursor_for_pos(pos)
        if not cursor:
            return None
        return cursor.position()

    def _close_popup(self, *, reset_pressed: bool = True) -> None:
        if not self._popup:
            return
        popup = self._popup
        self._popup = None
        if sip is not None:
            try:
                if sip.isdeleted(popup):
                    return
            except RuntimeError:
                return
        with suppress(RuntimeError):
            popup.blockSignals(True)
        try:
            with suppress(RuntimeError):
                popup.close()
        finally:
            with suppress(RuntimeError):
                popup.blockSignals(False)
        if self._global_filter_active and self._app:
            with suppress(RuntimeError, TypeError):
                self._app.removeEventFilter(self)
            self._global_filter_active = False
        if reset_pressed:
            self._reset_pressed_match()
        self._reevaluate_hover_state()

    def _on_matches_changed(self, document_id: str) -> None:
        if document_id != self._document_id:
            return

    def _on_widget_destroyed(self) -> None:
        try:
            self._registry.matches_changed.disconnect(self._on_matches_changed)
        except (TypeError, RuntimeError):
            pass
        set_dynamic_clickable(self._viewport, False)
        self._close_popup()

    def _on_popup_destroyed(self) -> None:
        self._popup = None
        if self._global_filter_active and self._app:
            with suppress(RuntimeError, TypeError):
                self._app.removeEventFilter(self)
            self._global_filter_active = False
        self._reevaluate_hover_state()

    def _update_hover_clickable(self, pos: Optional[QPoint]) -> None:
        # Reuse existing logic for detecting a match at the position so the
        # cursor-change and hover shading use the same source of truth.
        match = self._match_at_position(pos) if pos is not None else None
        is_clickable = bool(match)
        if is_clickable != self._hover_clickable:
            self._hover_clickable = is_clickable
            set_dynamic_clickable(self._viewport, is_clickable)

        # Determine hovered absolute range (from the registry entry) and
        # update the document highlighter.
        hovered_range = (match.get("start", 0), match.get("length", 0)) if match else None

        # Find the corresponding highlighter and inform it of the hovered range.
        if hasattr(self._service, "_highlighters"):
            for h in self._service._highlighters:
                if h.document_id() == self._document_id:
                    if hovered_range:
                        h.set_hovered_range(hovered_range[0], hovered_range[1])
                    else:
                        h.set_hovered_range(None, None)
                    break

    def _update_hover_from_global(self, global_pos: QPoint) -> None:
        if not getattr(self, "_viewport", None):
            return
        local_pos = self._viewport.mapFromGlobal(global_pos)
        if self._viewport.rect().contains(local_pos):
            self._update_hover_clickable(local_pos)
        else:
            self._update_hover_clickable(None)

    def _reevaluate_hover_state(self) -> None:
        try:
            global_pos = QCursor.pos()
        except RuntimeError:
            self._update_hover_clickable(None)
            return
        self._update_hover_from_global(global_pos)


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
        self._click_controllers: Dict[str, MatchClickController] = {}
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

    def attach_highlighter(
        self,
        document: QTextDocument,
        document_id: str,
        underline_color: Optional[QColor] = None,
        text_widget: Optional[QWidget] = None,
    ) -> TrackedMatchHighlighter:
        highlighter = TrackedMatchHighlighter(document, self._matcher, self.registry, document_id, underline_color)
        self._highlighters.append(highlighter)
        if text_widget is not None:
            if document_id in self._click_controllers:
                self._click_controllers[document_id].shutdown()
            controller = MatchClickController(text_widget, document_id, self.registry, self)
            self._click_controllers[document_id] = controller
        return highlighter

    def detach_highlighter(self, highlighter: TrackedMatchHighlighter) -> None:
        if highlighter in self._highlighters:
            self._highlighters.remove(highlighter)
            self.registry.clear_document(highlighter.document_id())
        controller = self._click_controllers.pop(highlighter.document_id(), None)
        if controller:
            controller.shutdown()

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

    def handle_entry_activation(self, entry_name: str, entry_uuid: str) -> None:
        parent = self.parent()
        window = getattr(parent, "enhanced_window", None)
        if window:
            window.open_with_entry(self.project_name, entry_name)
            window.raise_()
            window.activateWindow()

    def _extract_terms(self, data: Dict) -> List[TermInfo]:
        terms: List[TermInfo] = []
        seen_entries: Dict[Tuple[str, str], bool] = {}
        categories = data.get("categories", []) or []
        extensions_entries = data.get("extensions", {}).get("entries", {}) if data else {}

        for category in categories:
            category_name = (category.get("name") or "").strip() or "Unknown"
            for entry in category.get("entries", []) or []:
                entry_name = (entry.get("name") or "").strip()
                if not entry_name:
                    continue
                entry_uuid = entry.get("uuid", "")
                content = entry.get("content", {})
                if isinstance(content, dict):
                    description = content.get("description", "") or ""
                else:
                    description = str(content) if content else ""
                extended = extensions_entries.get(entry_name, {})
                track = extended.get("track_by_name", True)
                if not track:
                    continue

                self._append_term(
                    terms,
                    seen_entries,
                    entry_name,
                    entry_uuid,
                    category_name,
                    description,
                    entry_name,
                    "name",
                )
                for alias in self._normalize_aliases(extended.get("aliases")):
                    if alias:
                        self._append_term(
                            terms,
                            seen_entries,
                            entry_name,
                            entry_uuid,
                            category_name,
                            description,
                            alias,
                            "alias",
                        )
        return terms

    def _append_term(
        self,
        terms: List[TermInfo],
        seen_entries: Dict[Tuple[str, str], bool],
        entry_name: str,
        entry_uuid: str,
        category_name: str,
        description: str,
        term: str,
        source: str,
    ) -> None:
        key = (entry_uuid or entry_name, term)
        if key in seen_entries:
            return
        seen_entries[key] = True
        terms.append(
            TermInfo(
                entry_name=entry_name,
                entry_uuid=entry_uuid or entry_name,
                category_name=category_name,
                description=description,
                term=term,
                source=source,
            )
        )

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