import os
import glob
import re
import sys
import json

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QToolBar, QAction, QColorDialog,
    QFontComboBox, QComboBox, QLabel, QMessageBox, QTextEdit, QStyle, QShortcut
)
from PyQt5.QtCore import Qt, QTimer, QObject, QEvent
from PyQt5.QtGui import QFont, QTextCursor, QColor, QTextCharFormat, QTextBlockFormat, QPen, QKeySequence, QIcon, QPixmap

# Translation function fallback
import builtins
if not hasattr(builtins, '_'):
    def _(text):
        return text
    builtins._ = _

from .focus_mode import PlainTextEdit
from spylls.hunspell import Dictionary
from util.find_dialog import FindDialog
from settings.theme_manager import ThemeManager
from util.color_manager import ColorManager


class AutoIndentTextEdit(PlainTextEdit):
    """Custom text edit that supports auto-indentation for new lines and selections."""

    def __init__(self, scene_editor):
        super().__init__()
        self.scene_editor = scene_editor
        self.auto_indent_enabled = False
        self.installEventFilter(self)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_auto_indent_enabled(self, enabled: bool):
        self.auto_indent_enabled = enabled

    def apply_auto_indent_to_selection(self):
        """Indent the currently selected lines once when enabling auto indent."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False

        if self._selection_already_indented(cursor):
            return False

        self._indent_selection(cursor, only_missing=True)
        return True

    def indent_selection_or_block(self, only_missing: bool = False) -> bool:
        """Indent the current selection or single block."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            self._indent_selection(cursor, only_missing=only_missing)
            return True
        return self._indent_current_block(only_missing=only_missing)

    def unindent_selection_or_block(self) -> bool:
        """Remove a single level of indentation from the selection or block."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return self._unindent_selection(cursor)
        return self._unindent_current_block()

    def selection_or_block_is_indented(self) -> bool:
        """Determine if the current selection (or block) starts with an indent unit."""
        cursor = self.textCursor()
        indent_unit = self._indent_unit()
        if cursor.hasSelection():
            start, end, start_block, end_block = self._selection_blocks(cursor)
            if start_block is None:
                return False

            block = start_block
            while block.isValid():
                if not self._block_has_indent(block, indent_unit):
                    return False
                if block == end_block:
                    break
                block = block.next()
            return True

        block = cursor.block()
        return self._block_has_indent(block, indent_unit)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj == self and event.type() == QEvent.KeyPress and self.auto_indent_enabled:
            key = event.key()

            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._insert_newline_with_indent()
                return True

            if key == Qt.Key_Tab:
                cursor = self.textCursor()
                if cursor.hasSelection():
                    self._indent_selection(cursor)
                else:
                    cursor.insertText(self._indent_unit())
                return True

            if key == Qt.Key_Backtab:
                cursor = self.textCursor()
                if cursor.hasSelection():
                    self._unindent_selection(cursor)
                else:
                    self._unindent_at_cursor()
                return True

        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _indent_unit(self) -> str:
        return "    "  # Four spaces as a standard indentation unit

    def _leading_whitespace(self, text: str) -> str:
        match = re.match(r"^[ \t]*", text)
        return match.group(0) if match else ""

    def _insert_newline_with_indent(self):
        cursor = self.textCursor()
        block = cursor.block()
        current_indent = self._leading_whitespace(block.text())
        if not current_indent:
            current_indent = self._indent_unit()

        cursor.beginEditBlock()
        cursor.insertText("\n" + current_indent)
        cursor.endEditBlock()

    def _indent_selection(self, cursor: QTextCursor, only_missing: bool = False):
        indent_unit = self._indent_unit()
        start, end, start_block, end_block = self._selection_blocks(cursor)
        if start_block is None:
            return

        cursor.beginEditBlock()
        block = start_block
        while block.isValid():
            block_cursor = QTextCursor(block)
            block_cursor.movePosition(QTextCursor.StartOfBlock)
            if not only_missing or not self._block_has_indent(block, indent_unit):
                block_cursor.insertText(indent_unit)
            if block == end_block:
                break
            block = block.next()
        cursor.endEditBlock()

        # Restore cursor without preserving original selection (simpler UX)
        new_cursor = self.textCursor()
        new_cursor.setPosition(end_block.position() + len(end_block.text()))
        self.setTextCursor(new_cursor)

    def _indent_current_block(self, only_missing: bool = False) -> bool:
        indent_unit = self._indent_unit()
        cursor = self.textCursor()
        block = cursor.block()
        if block is None:
            return False
        if only_missing and self._block_has_indent(block, indent_unit):
            return False

        original_position = cursor.position()
        block_start = block.position()
        offset = original_position - block_start

        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.StartOfBlock)
        cursor.insertText(indent_unit)
        cursor.endEditBlock()

        new_cursor = self.textCursor()
        new_cursor.setPosition(block_start + len(indent_unit) + offset)
        self.setTextCursor(new_cursor)
        return True

    def _unindent_selection(self, cursor: QTextCursor):
        indent_unit = self._indent_unit()
        indent_len = len(indent_unit)
        start, end, start_block, end_block = self._selection_blocks(cursor)
        if start_block is None:
            return False

        changed = False
        cursor.beginEditBlock()
        block = start_block
        while block.isValid():
            removed = self._remove_leading_indent(block, indent_unit, indent_len)
            if removed:
                changed = True
            if block == end_block:
                break
            block = block.next()
        cursor.endEditBlock()

        new_cursor = self.textCursor()
        new_cursor.setPosition(end_block.position() + len(end_block.text()))
        self.setTextCursor(new_cursor)
        return changed

    def _unindent_at_cursor(self):
        cursor = self.textCursor()
        block = cursor.block()
        indent_unit = self._indent_unit()
        indent_len = len(indent_unit)
        original_position = cursor.position()
        block_start = block.position()

        cursor.beginEditBlock()
        removed = self._remove_leading_indent(block, indent_unit, indent_len)
        cursor.endEditBlock()

        if removed:
            new_cursor = self.textCursor()
            new_block_start = new_cursor.block().position()
            offset = max(0, (original_position - block_start) - removed)
            new_cursor.setPosition(new_block_start + offset)
            self.setTextCursor(new_cursor)

    def _unindent_current_block(self) -> bool:
        cursor = self.textCursor()
        block = cursor.block()
        if block is None:
            return False
        indent_unit = self._indent_unit()
        indent_len = len(indent_unit)
        original_position = cursor.position()
        block_start = block.position()

        cursor.beginEditBlock()
        removed = self._remove_leading_indent(block, indent_unit, indent_len)
        cursor.endEditBlock()

        if not removed:
            return False

        new_cursor = self.textCursor()
        new_block_start = new_cursor.block().position()
        offset = max(0, (original_position - block_start) - removed)
        new_cursor.setPosition(new_block_start + offset)
        self.setTextCursor(new_cursor)
        return True

    def _remove_leading_indent(self, block, indent_unit, indent_len):
        text = block.text()
        block_cursor = QTextCursor(block)
        block_cursor.movePosition(QTextCursor.StartOfBlock)

        if text.startswith(indent_unit):
            block_cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor, indent_len)
            block_cursor.removeSelectedText()
            return indent_len

        if text.startswith("\t"):
            block_cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor, 1)
            block_cursor.removeSelectedText()
            return 1

        spaces = len(text) - len(text.lstrip(" "))
        if spaces:
            block_cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor, min(spaces, indent_len))
            block_cursor.removeSelectedText()
            return min(spaces, indent_len)

        return 0

    def _selection_blocks(self, cursor: QTextCursor):
        if not cursor.hasSelection():
            return None, None, None, None

        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        document = self.document()
        start_block = document.findBlock(start)
        end_position = max(start, end - 1)
        end_block = document.findBlock(end_position)
        return start, end, start_block, end_block

    def _block_has_indent(self, block, indent_unit: str) -> bool:
        text = block.text()
        if not text:
            return False
        if text.startswith(indent_unit) or text.startswith("\t"):
            return True
        return False

    def _selection_already_indented(self, cursor: QTextCursor) -> bool:
        indent_unit = self._indent_unit()
        start, end, start_block, end_block = self._selection_blocks(cursor)
        if start_block is None:
            return False

        block = start_block
        while block.isValid():
            if not self._block_has_indent(block, indent_unit):
                return False
            if block == end_block:
                break
            block = block.next()
        return True


class SceneEditor(QWidget):
    """Scene editor with toolbar, text area, and spellchecking support."""

    def __init__(self, controller, tint_color=QColor("black")):
        super().__init__()
        self.controller = controller
        self.tint_color = tint_color
        self.suppress_updates = False

        # Setup dictionary path
        base_module = sys.modules[self.__module__].__file__
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(base_module)))
        self.dict_dir = os.path.join(project_dir, "assets", "dictionaries")

        self.languages = {}
        self.dictionary = None
        self.extra_selections = []
        self.settings_file = os.path.join(self.dict_dir, "editor_settings.json")
        self.saved_language = "Off"
        
        # Load saved language preference if available
        self.load_language_preference()

        # --- Initialize ColorManager here ---
        settings_path = os.path.join(self.dict_dir, "color_settings.json")
        self.color_manager = ColorManager(settings_path)

        self.shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut_find.activated.connect(self.open_find_dialog)
        self.find_dialog = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.toolbar = QToolBar("Editor Toolbar")
        self.editor = AutoIndentTextEdit(self)

        self.setup_toolbar()
        self.setup_editor()

        layout.addWidget(self.toolbar)
        layout.addWidget(self.editor)
        layout.setContentsMargins(0, 0, 0, 0)

        self.load_languages()

    def setup_toolbar(self):
        self.toolbar.setStyleSheet("")  # Reset any custom styles to use theme
        # Formatting actions
        for name, icon, tip, func, check in [
            ("bold",      "assets/icons/bold.svg",      _("Bold"),               self.controller.toggle_bold,      True),
            ("italic",    "assets/icons/italic.svg",    _("Italic"),             self.controller.toggle_italic,    True),
            ("underline", "assets/icons/underline.svg", _("Underline"),          self.controller.toggle_underline, True),
            ("color",     QIcon(QPixmap("assets/icons/color.svg")), _("Color"), self.on_color_action, False)
        ]:
            setattr(self, f"{name}_action", self.add_action(name, icon, tip, func, check))
        self.toolbar.addSeparator()

        # TTS
        self.tts_action = self.add_action(
            "tts", "assets/icons/play-circle.svg", _("Play TTS (or Stop)"),
            self.controller.toggle_tts, False
        )
        self.toolbar.addSeparator()

        # Alignment
        for name, icon, tip, func in [
            ("align_left", "assets/icons/align-left.svg", _("Align Left"), self.controller.align_left),
            ("align_center", "assets/icons/align-center.svg", _("Center Align"), self.controller.align_center),
            ("align_right", "assets/icons/align-right.svg", _("Align Right"), self.controller.align_right)
        ]:
            setattr(self, f"{name}_action", self.add_action(name, icon, tip, func, False))

        self.toolbar.addSeparator()
        # Font selection
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(self.controller.update_font_family)
        self.toolbar.addWidget(self.font_combo)

        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems([str(s) for s in [10,12,14,16,18,20,24,28,32]])
        self.font_size_combo.setCurrentText("12")
        self.font_size_combo.currentIndexChanged.connect(
            lambda: self.controller.set_font_size(int(self.font_size_combo.currentText()))
        )
        self.font_size_combo.setMinimumWidth(60)
        self.toolbar.addWidget(self.font_size_combo)
        
        # Line spacing
        self.toolbar.addWidget(QLabel(_("Line:")))
        self.line_spacing_combo = QComboBox()
        self.line_spacing_combo.setEditable(True)  # Allow custom values
        self.line_spacing_combo.addItems(["1.0", "1.15", "1.5", "2.0", "2.5", "3.0"])
        self.line_spacing_combo.setCurrentText("1.15")
        self.line_spacing_combo.currentTextChanged.connect(self.controller.set_line_spacing)
        self.line_spacing_combo.setMinimumWidth(60)
        self.line_spacing_combo.setToolTip(_("Line spacing (e.g., 1.0, 1.5, 2.0)"))
        self.toolbar.addWidget(self.line_spacing_combo)
        
        # Paragraph spacing
        self.toolbar.addWidget(QLabel(_("Para:")))
        self.paragraph_spacing_combo = QComboBox()
        self.paragraph_spacing_combo.setEditable(True)  # Allow custom values
        self.paragraph_spacing_combo.addItems(["0", "6", "12", "18", "24"])
        self.paragraph_spacing_combo.setCurrentText("12")
        self.paragraph_spacing_combo.currentTextChanged.connect(self.controller.set_paragraph_spacing)
        self.paragraph_spacing_combo.setMinimumWidth(50)
        self.paragraph_spacing_combo.setToolTip(_("Paragraph spacing in pixels (e.g., 0, 12, 24)"))
        self.toolbar.addWidget(self.paragraph_spacing_combo)
        
        # Auto indent toggle
        self.auto_indent_action = self.add_action(
            "auto_indent",
            "assets/icons/list.svg",
            _("Toggle indentation for the current line or selection."),
            self.controller.toggle_auto_indent,
            True
        )
        self.auto_indent_action.setChecked(False)

        self.toolbar.addSeparator()

        # Scene-specific
        for name, icon, tip, func in [
            ("manual_save","assets/icons/save.svg",_("Manual Save"),self.controller.manual_save_scene),
            ("oh_shit","assets/icons/share.svg",_("Show Backups"),self.controller.on_oh_shit),
            ("analysis_editor","assets/icons/feather.svg",_("Analysis Editor"),self.controller.open_analysis_editor),
        ]:
            setattr(self, f"{name}_action", self.add_action(name, icon, tip, func, False))

        self.toolbar.addSeparator()
        # Language combo
        self.toolbar.addWidget(QLabel(_("Spell check:")))
        self.lang_combo = QComboBox()
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        self.toolbar.addWidget(self.lang_combo)

    def add_action(self, name, icon, tooltip, callback, checkable=False):
        """
        Adds a toolbar action. 
        - If `icon` is a QIcon, use it directly (preserving original colors).
        - If `icon` is a string path, pass it through ThemeManager.get_tinted_icon.
        """
        if isinstance(icon, QIcon):
            action_icon = icon
        else:
            action_icon = ThemeManager.get_tinted_icon(icon, self.tint_color)

        action = QAction(action_icon, "", self)
        action.setToolTip(tooltip)
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        self.toolbar.addAction(action)
        return action

    def setup_editor(self):
        e = self.editor
        e.setPlaceholderText(_("Select a node to edit..."))
        e.setContextMenuPolicy(Qt.CustomContextMenu)
        e.customContextMenuRequested.connect(self.show_context_menu)
        e.textChanged.connect(self.controller.on_editor_text_changed)
        e.textChanged.connect(self.start_spellcheck_timer)
        e.cursorPositionChanged.connect(self.update_toolbar_state)
        e.selectionChanged.connect(self.update_toolbar_state)
        


        # Adjust viewport margins to prevent scrollbar from obscuring content
        scrollbar_width = e.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        e.setViewportMargins(0, 0, scrollbar_width, 0)  # Reserve space on the right for scrollbar

        # Spellcheck timer
        self.spellcheck_timer = QTimer(self)
        self.spellcheck_timer.setSingleShot(True)
        self.spellcheck_timer.setInterval(500)
        self.spellcheck_timer.timeout.connect(self.check_spelling)
        
        # Set a callback to check spelling when content is loaded
        QTimer.singleShot(500, self.delayed_initial_check)

    def on_color_action(self):
        """
        Show a single QColorDialog for foreground only, then apply it to the selected text.
        """
        # 1) Ask user for a new foreground color:
        col = QColorDialog.getColor(
            self.color_manager.default_fg,
            self,
            "Select Text Color",
            QColorDialog.ShowAlphaChannel
        )
        if not col.isValid():
            return

        # 2) Update default in ColorManager and save (background stays unchanged):
        self.color_manager.default_fg = col
        self.color_manager.save_colors(self.color_manager.default_fg, self.color_manager.default_bg)

        # 3) Apply only the foreground color to the current selection:
        self.color_manager.apply_fg_to_selection(self.editor, col)

    def load_languages(self):
        self.languages.clear()
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self.lang_combo.addItem("Off")

        # Populate from .aff/.dic pairs
        for aff in glob.glob(os.path.join(self.dict_dir, '*.aff')):
            code = os.path.splitext(os.path.basename(aff))[0]
            dic = os.path.join(self.dict_dir, f"{code}.dic")
            if os.path.isfile(dic):
                self.languages[code] = code
                self.lang_combo.addItem(code)

        # Add Other entry at bottom
        self.lang_combo.addItem("Other")

        # Restore saved
        saved_index = self.lang_combo.findText(self.saved_language)
        if saved_index >= 0:
            self.lang_combo.setCurrentIndex(saved_index)
        else:
            self.lang_combo.setCurrentIndex(0)
        self.lang_combo.blockSignals(False)

        # Apply saved if not Off/Other
        if self.saved_language not in ("Off", "Other"):
            self.apply_saved_language()

    def on_language_changed(self, idx):
        lang = self.lang_combo.currentText()

        # We turn off the check
        if lang == "Off":
            self.dictionary = None
            self.clear_spellcheck_highlights()
            self.save_language_preference(lang)
            return

        # Handling “Other” items
        if lang == "Other":
            dlg = QMessageBox(self)
            dlg.setWindowTitle(_("Additional Dictionaries"))
            dlg.setTextFormat(Qt.RichText)
            dlg.setTextInteractionFlags(Qt.TextBrowserInteraction)
            dlg.setText(_(
                "For more dictionaries, please visit:<br>"
                "<a href=\"https://github.com/LibreOffice/dictionaries\">"
                "https://github.com/LibreOffice/dictionaries</a><br>"
                "Paste the .aff and .dic file into the folder:<br>"
                "Writingway/assets/dictionaries"
            ))
            dlg.exec_()
            prev = self.saved_language if self.saved_language in self.languages else "Off"
            self.lang_combo.setCurrentText(prev)
            return

        # Build full path (without extension) to the .aff/.dic files
        dict_base = os.path.join(self.dict_dir, lang)
        try:
            # Load the dictionary from "<dict_base>.aff" and "<dict_base>.dic"
            self.dictionary = Dictionary.from_files(dict_base)
            # Run spell‑check immediately
            self.check_spelling()
            # Remember selection
            self.save_language_preference(lang)
        except Exception as e:
            QMessageBox.critical(
                self,
                _("Error"),
                _(f"Cannot load {lang}: {e}")
            )
            self.dictionary = None
            self.clear_spellcheck_highlights()
        
    def save_language_preference(self, lang):
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            settings = {"language": lang}
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f)
            self.saved_language = lang
        except Exception as e:
            print(f"Error saving language preference: {e}")
            
    def load_language_preference(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.saved_language = settings.get("language", "Off")
        except Exception as e:
            print(f"Error loading language preference: {e}")
            
    def apply_saved_language(self):
        if self.saved_language not in self.languages:
            return

        # Build full path (without extension) to the .aff/.dic files
        dict_base = os.path.join(self.dict_dir, self.saved_language)
        try:
            # Load the dictionary from "<dict_base>.aff" and "<dict_base>.dic"
            self.dictionary = Dictionary.from_files(dict_base)
            # If there's already text in the editor, highlight misspellings right away
            if self.editor.toPlainText():
                self.check_spelling()
        except Exception as e:
            print(f"Error loading dictionary {self.saved_language}: {e}")

    def clear_spellcheck_highlights(self):
        self.extra_selections = []
        self.editor.setExtraSelections([])

    def start_spellcheck_timer(self):
        if self.dictionary:
            self.spellcheck_timer.start()

    def check_spelling(self):
        """Check spelling and highlight misspelled words with improved visibility."""
        if not self.dictionary:
            return
        text = self.editor.toPlainText()
        self.extra_selections = []
        
        # Create enhanced format for spelling errors
        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
        fmt.setUnderlineColor(QColor(255, 0, 0))  # Bright red
        
        # Make underline thicker with pen
        pen = QPen(QColor(255, 0, 0))
        pen.setWidth(2)  # Thicker underline
        fmt.setUnderlineColor(pen.color())
        
        # Use improved regex for word detection that can handle apostrophes and hyphens
        # This matches words and contractions better than the simple \w+ pattern
        word_pattern = r'\b[a-zA-Z]+[\'-]?[a-zA-Z]*\b'
        
        for m in re.finditer(word_pattern, text):
            w = m.group()
            if not self.dictionary.lookup(w):
                cur = QTextCursor(self.editor.document())
                cur.setPosition(m.start())
                cur.setPosition(m.end(), QTextCursor.KeepAnchor)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cur
                sel.format = fmt
                self.extra_selections.append(sel)
        self.editor.setExtraSelections(self.extra_selections)

    def show_context_menu(self, pos):
        menu = self.editor.createStandardContextMenu(pos)
        cur = self.editor.textCursor()
        if cur.hasSelection():
            act = menu.addAction(_("Rewrite"))
            act.triggered.connect(self.controller.rewrite_selected_text)
        if self.dictionary:
            wc = self.editor.cursorForPosition(pos)
            wc.select(QTextCursor.WordUnderCursor)
            w = wc.selectedText()
            if w and not self.dictionary.lookup(w):
                sugs = self.dictionary.suggest(w)
                if sugs:
                    sm = menu.addMenu(_("Suggestions"))
                    for s in sugs:
                        a = sm.addAction(s)
                        a.triggered.connect(lambda _, s=s, c=wc: self.replace_word(c, s))
                else:
                    menu.addAction(_("(No suggestions)"))
        menu.exec_(self.editor.mapToGlobal(pos))

    def replace_word(self, cursor, new):
        cursor.insertText(new)
        self.check_spelling()

    def update_toolbar_state(self):
        if self.suppress_updates:
            return
        self.suppress_updates = True
        cur = self.editor.textCursor()
        if cur.hasSelection():
            fm = self.get_selection_formats(cur.selectionStart(), cur.selectionEnd())
            self.update_toggles_for_selection(fm)
        else:
            cf = self.editor.currentCharFormat()
            self.update_toggles(cf)
        
        # Update alignment buttons
        aln = cur.blockFormat().alignment()
        self.align_left_action.setChecked(aln == Qt.AlignLeft)
        self.align_center_action.setChecked(aln == Qt.AlignCenter)
        self.align_right_action.setChecked(aln == Qt.AlignRight)
        
        # Update line spacing and paragraph spacing controls
        self.update_spacing_controls(cur)

        # Update auto-indent toggle to reflect current block/selection
        is_indented = self.editor.selection_or_block_is_indented()
        self.auto_indent_action.blockSignals(True)
        self.auto_indent_action.setChecked(is_indented)
        self.auto_indent_action.blockSignals(False)

        self.suppress_updates = False

    def update_spacing_controls(self, cursor):
        """Update line spacing and paragraph spacing controls based on current cursor position."""
        block_format = cursor.blockFormat()
        
        # Update line spacing combo
        line_height = block_format.lineHeight()
        if line_height > 0:
            if block_format.lineHeightType() == QTextBlockFormat.ProportionalHeight:
                spacing_value = line_height / 100.0
                spacing_text = f"{spacing_value:.2f}".rstrip('0').rstrip('.')
                self.line_spacing_combo.blockSignals(True)
                self.line_spacing_combo.setCurrentText(spacing_text)
                self.line_spacing_combo.blockSignals(False)
        
        # Update paragraph spacing combo
        bottom_margin = block_format.bottomMargin()
        margin_text = str(int(bottom_margin))
        self.paragraph_spacing_combo.blockSignals(True)
        self.paragraph_spacing_combo.setCurrentText(margin_text)
        self.paragraph_spacing_combo.blockSignals(False)
        
        # Update font combo to show current font
        char_format = cursor.charFormat()
        current_font = char_format.font()
        if current_font.family():
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentFont(current_font)
            self.font_combo.blockSignals(False)

    def get_selection_formats(self, start, end):
        """
        Returns a list of character formats for each character in the start-end range.
        Used to analyze the formatting of the selected text.
        """
        formats = []
        cursor = self.editor.textCursor()
        for pos in range(start, end):
            cursor.setPosition(pos)
            formats.append(cursor.charFormat())
        return formats

    def delayed_initial_check(self):
        """Perform a delayed initial spell check to make sure content is loaded."""
        if self.dictionary and self.editor and self.editor.toPlainText():
            self.check_spelling()

    def update_toggles(self, cf):
        self.bold_action.setChecked(cf.fontWeight() >= QFont.Bold)
        self.italic_action.setChecked(cf.fontItalic())
        self.underline_action.setChecked(cf.fontUnderline())

    def update_toggles_for_selection(self, formats):
        """
        formats: a list of QTextCharFormat objects for each character in the selection.
        Checks if all characters have the same style (bold, italic, underline).
        """
        # If no formats, exit
        if not formats:
            return

        # Get the state of the first character as a reference
        first_format = formats[0]
        first_bold = first_format.font().bold()
        first_italic = first_format.font().italic()
        first_underline = first_format.font().underline()

        # Check that all characters have the same style as the first one
        all_bold = all(fmt.font().bold() == first_bold for fmt in formats)
        all_italic = all(fmt.font().italic() == first_italic for fmt in formats)
        all_underline = all(fmt.font().underline() == first_underline for fmt in formats)

        # Set the state of the buttons
        self.bold_action.setChecked(all_bold and first_bold)
        self.italic_action.setChecked(all_italic and first_italic)
        self.underline_action.setChecked(all_underline and first_underline)

    def update_tint(self, tint_color):
        self.tint_color = tint_color
        # Update formatting actions
        formatting_actions = [
            ("bold", "assets/icons/bold.svg"),
            ("italic", "assets/icons/italic.svg"),
            ("underline", "assets/icons/underline.svg")
        ]
        for name, path in formatting_actions:
            action = getattr(self, f"{name}_action", None)
            if action:
                action.setIcon(ThemeManager.get_tinted_icon(path, tint_color))
        
        # Update TTS action
        tts_action = getattr(self, "tts_action", None)
        if tts_action:
            tts_action.setIcon(ThemeManager.get_tinted_icon("assets/icons/play-circle.svg", tint_color))
        
        # Update alignment actions
        alignment_actions = [
            ("align_left", "assets/icons/align-left.svg"),
            ("align_center", "assets/icons/align-center.svg"),
            ("align_right", "assets/icons/align-right.svg")
        ]
        for name, path in alignment_actions:
            action = getattr(self, f"{name}_action", None)
            if action:
                action.setIcon(ThemeManager.get_tinted_icon(path, tint_color))
        
        # Update scene-specific actions
        scene_actions = [
            ("manual_save", "assets/icons/save.svg"),
            ("oh_shit", "assets/icons/share.svg"),
            ("analysis_editor", "assets/icons/feather.svg"),
            ("auto_indent", "assets/icons/list.svg")
        ]
        for name, path in scene_actions:
            action = getattr(self, f"{name}_action", None)
            if action:
                action.setIcon(ThemeManager.get_tinted_icon(path, tint_color))
            
    def open_find_dialog(self):
        if self.find_dialog is None:
            self.find_dialog = FindDialog(self.editor, self)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.search_field.setFocus()
