#!/usr/bin/env python3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QStackedWidget, QHBoxLayout, QPushButton, 
                            QTextEdit, QComboBox, QSizePolicy,
                            QFormLayout, QSplitter, QCheckBox, QLineEdit, QLabel, QTabWidget, QTabBar)
from PyQt5.QtGui import QPainter
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QStyle, QStyleOptionTab
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QVariant
from settings.theme_manager import ThemeManager
# from .summary_controller import SummaryController, SummaryMode
# from .summary_model import SummaryModel
from muse.prompt_panel import PromptPanel
from muse.prompt_preview_dialog import PromptPreviewDialog
from muse.prompt_variables import get_prompt_variables
from project_window.llm_panel import LLMPanel
from project_window.chapter_summary_panel import ChapterSummaryPanel
from copy import deepcopy

# gettext '_' fallback for static analysis / standalone edits
_ = globals().get('_', lambda s: s)

class RightStack(QWidget):
    """Stacked widget for summary and LLM panels."""
    def __init__(self, controller, model, tint_color=QColor("black")):
        super().__init__()
        self.controller = controller
        self.model = model
        self.tint_color = tint_color
        self.stack = QStackedWidget()
        self.scene_editor = controller.scene_editor

        # Temporary prompt config management
        self._suspend_temp_sync = False

        self.init_ui()
        self.project_tree = controller.project_tree

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)
        layout.setContentsMargins(0, 0, 0, 0)

        self.summary_panel = self.create_summary_panel()
        self.llm_panel = self.create_llm_panel()
        self.stack.addWidget(self.summary_panel)
        self.stack.addWidget(self.llm_panel)

    def _on_tab_changed(self, index):
        """Called by LLMPanel when the prompt tab widget changes tabs."""
        try:
            if index == getattr(self, 'write_tab_index', None):
                mode = 'write'
            elif index == getattr(self, 'rewrite_tab_index', None):
                mode = 'rewrite'
            else:
                mode = 'summarize'
            self._set_active_mode(mode)
        except Exception:
            pass

    def create_summary_panel(self):
        panel = ChapterSummaryPanel(self.controller, self.tint_color)
        self.chapter_summary_panel = panel
        return panel

    def create_llm_panel(self):
        return LLMPanel(self)

    def prepare_chapter_view(self):
        """Move shared preview and controls into the chapter panel and use the chapter prompt panel."""
        try:
            if not hasattr(self, 'chapter_summary_panel') or not hasattr(self, 'preview_stack'):
                return
            layout = self.chapter_summary_panel.preview_placeholder.layout()
            if layout is None:
                layout = QVBoxLayout(self.chapter_summary_panel.preview_placeholder)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

            # Reparent preview stack and controls
            self._move_widget_to_layout(self.preview_stack, layout, 0)
            # Hide preview actions in chapter view
            try:
                if getattr(self, 'preview_actions_widget', None):
                    self.preview_actions_widget.setParent(None)
            except Exception:
                pass
            if getattr(self, 'prompt_controls_widget', None):
                self._move_widget_to_layout(self.prompt_controls_widget, layout, 1)

            # Use the chapter prompt panel for summarize mode
            if hasattr(self, 'prompt_modes') and 'summarize' in self.prompt_modes:
                self._orig_summarize_panel = self.prompt_modes['summarize']['prompt_panel']
                self.prompt_modes['summarize']['prompt_panel'] = self.chapter_summary_panel.prompt_panel
            self._set_active_mode('summarize')
        except Exception as e:
            print(f"prepare_chapter_view error: {e}")

    def prepare_llm_view(self):
        """Restore shared widgets to the LLM panel and the original summarize prompt panel."""
        try:
            if hasattr(self, '_orig_summarize_panel') and hasattr(self, 'prompt_modes') and 'summarize' in self.prompt_modes:
                self.prompt_modes['summarize']['prompt_panel'] = self._orig_summarize_panel
                delattr(self, '_orig_summarize_panel')
            # Re-embed into current active tab (default to write)
            target_mode = getattr(self, 'active_mode', 'write')
            if target_mode not in ('write', 'rewrite', 'summarize'):
                target_mode = 'write'
            self._embed_shared_widgets(target_mode)
        except Exception as e:
            print(f"prepare_llm_view error: {e}")

    def add_combo(self, layout, label_text, items, callback):
        combo = QComboBox()
        combo.addItems(items)
        combo.currentIndexChanged.connect(callback)
        layout.addRow(f"{label_text}:", combo)
        return combo

    def _set_bottom_row_dropdowns_enabled(self, enabled: bool):
        """Enable/disable bottom row dropdowns except provider/model combos."""
        state = self._get_state()
        panel = state['prompt_panel'] if state else None

        if panel and hasattr(panel, 'prompt_combo') and panel.prompt_combo:
            panel.prompt_combo.setEnabled(enabled)

        if self.active_mode == 'write':
            for combo in (self.pov_combo, self.pov_character_combo, self.tense_combo):
                if combo:
                    combo.setEnabled(enabled)

        # Provider and model selectors remain enabled regardless of preview state
        if panel:
            for combo in (getattr(panel, 'provider_combo', None), getattr(panel, 'model_combo', None)):
                if combo:
                    combo.setEnabled(True)
    
    def _apply_toggle_highlight_style(self):
        """Apply a consistent theme-derived highlight color to toggle buttons."""
        highlight_color = ThemeManager.get_toggle_highlight_color()
        if not highlight_color:
            return

        rgba = f"rgba({highlight_color.red()}, {highlight_color.green()}, {highlight_color.blue()}, {highlight_color.alpha()})"
        highlight_style = f"QPushButton:checked {{ background-color: {rgba}; }}"

        for button in (getattr(self, 'tweak_prompt_button', None),
                       getattr(self, 'preview_button', None),
                       getattr(self, 'context_toggle_button', None)):
            if button and button.isCheckable():
                button.setStyleSheet(highlight_style)

    def update_top_control_height(self):
        """Update the height of the top control container to the smaller of 250px or 20% of this widget's height."""
        try:
            if not hasattr(self, 'top_control_container') or not self.top_control_container:
                return
            total_h = self.height()
            cap_by_percent = int(total_h * 0.20)
            target = min(250, cap_by_percent)
            # Ensure at least a small visible height
            target = max(80, target)
            self.top_control_container.setMaximumHeight(target)
        except Exception:
            pass

    def resizeEvent(self, event):
        # Update top control height on resize and pass the event up
        self.update_top_control_height()
        super().resizeEvent(event)

    def update_tint(self, tint_color):
        self.tint_color = tint_color
        self.apply_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/save.svg", tint_color))
        self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg", tint_color))
        self.stop_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/x-octagon.svg", tint_color))
        self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon(
            "assets/icons/book-open.svg" if self.context_panel.isVisible() else "assets/icons/book.svg", tint_color))
        self.tweak_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/tool.svg", tint_color))
        self.refresh_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/refresh-cw.svg", tint_color))
        self.preview_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/eye.svg", tint_color))
        self.summary_preview_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/eye.svg", tint_color))
        self.summary_start_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/play-circle.svg", tint_color))
        self.delete_summary_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/trash.svg", tint_color))
        if self.pov_combo:
            self.pov_combo.setToolTip(_("POV: {}").format(self.model.settings.get('global_pov', 'Third Person')))
        if self.pov_character_combo:
            self.pov_character_combo.setToolTip(_("POV Character: {}").format(self.model.settings.get('global_pov_character', 'Character')))
        if self.tense_combo:
            self.tense_combo.setToolTip(_("Tense: {}").format(self.model.settings.get('global_tense', 'Present Tense')))

        self._apply_toggle_highlight_style()

    def _update_progress(self, message):
        self.controller.statusBar().showMessage(message, 5000)

    def _move_widget_to_layout(self, widget, layout, index):
        """Reparent a shared widget into the target layout at the desired position."""
        if not widget or not layout:
            return
        parent_widget = widget.parentWidget()
        if parent_widget and parent_widget.layout():
            parent_widget.layout().removeWidget(widget)
        target_parent = layout.parentWidget()
        if target_parent is not None:
            widget.setParent(target_parent)
        layout.insertWidget(index, widget)
        widget.show()

    def _embed_shared_widgets(self, mode):
        """Ensure the preview stack and button bar live inside the active tab."""
        layout = getattr(self, 'tab_layouts', {}).get(mode)
        if not layout or self.current_shared_mode == mode:
            return
        # Insert order: preview_stack (0), preview_actions_widget (1), prompt_controls_widget (2)
        self._move_widget_to_layout(self.preview_stack, layout, 0)

        # preview actions (apply + include) are not visible for summarize
        if getattr(self, 'preview_actions_widget', None):
            if mode not in ('summarize', 'chapter'):
                self.preview_actions_widget.setVisible(True)
                self._move_widget_to_layout(self.preview_actions_widget, layout, 1)
            else:
                # Remove/hide from layout if present
                try:
                    self.preview_actions_widget.setParent(None)
                except Exception:
                    pass

        if getattr(self, 'prompt_controls_widget', None):
            self._move_widget_to_layout(self.prompt_controls_widget, layout, 2)

        # connect preview changes to per-tab mirrors (if any)
        try:
            self.preview_text.textChanged.connect(self._on_shared_preview_changed)
        except Exception:
            pass

        self.current_shared_mode = mode

    def _on_shared_preview_changed(self):
        """Sync hook if we later mirror preview text into per-tab separate widgets."""
        # Currently we use a shared preview_text; placeholder for future per-tab mirroring
        return

    def apply_tab_preview(self):
        """Apply the preview text into the editor depending on the active tab.

        Beat (write): insert at cursor. Rewrite: replace selection. Summarize: no-op.
        """
        try:
            preview = self.preview_text.toPlainText()
            mode = getattr(self, 'active_mode', 'write')
            editor = getattr(self.scene_editor, 'editor', None)
            if not editor or not preview:
                return

            cursor = editor.textCursor()
            if mode in ('write', 'beat'):
                cursor.insertText(preview)
            elif mode == 'rewrite':
                if cursor.hasSelection():
                    cursor.insertText(preview)
                else:
                    # No selection — insert at cursor
                    cursor.insertText(preview)
            # For summarize, controls are hidden and no action is taken
        except Exception:
            return

    def toggle_context_panel(self):
        context_panel = self.context_panel
        if context_panel.isVisible():
            context_panel.setVisible(False)
            self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book.svg", self.tint_color))
        else:
            context_panel.build_project_tree()
            context_panel.build_compendium_tree()
            context_panel.setVisible(True)
            self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book-open.svg", self.tint_color))

    def get_additional_vars(self):
        """Get additional variables using the centralized variable system."""
        # The centralized system now handles all these variables automatically
        vars_dict = get_prompt_variables()
        
        # Merge in tweak values if they exist
        if hasattr(self, 'tweaks_widget'):
            tweak_values = self.tweaks_widget.get_tweak_values()
            vars_dict.update(tweak_values)

        if self.active_mode == 'rewrite' and hasattr(self, 'rewrite_tab') and self.rewrite_tab:
            selected_text = self.rewrite_tab.get_selected_text()
            if selected_text:
                vars_dict['selectedText'] = selected_text
        
        return vars_dict
    
    def _connect_edit_signals(self):
        """Connect signals for tracking edits to tweaks and preview widgets."""
        try:
            if hasattr(self, 'tweaks_widget'):
                instructions_edit = self.tweaks_widget.findChild(QTextEdit, "additional_instructions_edit")
                word_count_combo = self.tweaks_widget.findChild(QComboBox, "output_word_count_combo")
                
                if instructions_edit:
                    instructions_edit.textChanged.connect(self.on_temp_config_edited)
                if word_count_combo:
                    word_count_combo.currentTextChanged.connect(self.on_temp_config_edited)
            
            if hasattr(self, 'preview_editable_widget'):
                self.preview_editable_widget.contentEdited.connect(self.on_temp_config_edited)
        except Exception as e:
            print(f"Error connecting edit signals: {e}")
    
    def _get_state(self, mode=None):
        mode = mode or self.active_mode
        return self.prompt_modes.get(mode)

    def _ensure_state_initialized(self, mode=None):
        state = self._get_state(mode)
        if not state or state['initialized']:
            return
        self.reset_temporary_config(mode)

    def _update_custom_edits_indicator(self):
        state = self._get_state()
        self.custom_edits_label.setVisible(bool(state and state['has_custom_edits']))

    def _get_user_input_for_mode(self, mode):
        if mode == 'rewrite' and hasattr(self, 'rewrite_tab') and self.rewrite_tab:
            return self.rewrite_tab.get_selected_text()
        if mode == 'write' and hasattr(self, 'prompt_input') and self.prompt_input:
            return self.prompt_input.toPlainText().strip()
        return ""

    def get_selected_text_for_prompt(self) -> str:
        if hasattr(self, 'rewrite_tab') and self.active_mode == 'rewrite':
            text = self.rewrite_tab.get_selected_text()
            if text:
                return text

        try:
            cursor = self.scene_editor.editor.textCursor()
            if cursor and cursor.hasSelection():
                fragment = cursor.selection()
                return fragment.toPlainText().strip()
        except Exception:
            pass
        return ""

    def get_prompt_data(self):
        state = self._get_state()
        if not state:
            return {
                'user_input': "",
                'prompt_config': None,
                'overrides': {},
                'additional_vars': None,
                'current_scene_text': None,
                'extra_context': None,
            }

        prompt_config = None
        if state['has_custom_edits'] and state['temporary_prompt_config']:
            prompt_config = state['temporary_prompt_config']
        else:
            prompt_config = state['prompt_panel'].get_prompt()

        overrides = state['prompt_panel'].get_overrides() if hasattr(state['prompt_panel'], 'get_overrides') else {}
        user_input = self._get_user_input_for_mode(self.active_mode)
        additional_vars = self.get_additional_vars()

        return {
            'user_input': user_input,
            'prompt_config': prompt_config,
            'overrides': overrides,
            'additional_vars': additional_vars,
            'current_scene_text': None,
            'extra_context': None,
        }

    def _set_active_mode(self, mode):
        self.active_mode = mode
        is_prompt_mode = mode in self.prompt_modes

        self._embed_shared_widgets(mode)

        for button in (self.tweak_prompt_button, self.refresh_prompt_button, self.preview_button, self.send_button):
            if button:
                button.setEnabled(is_prompt_mode)
                button.setChecked(False)

        self.preview_stack.setCurrentWidget(self.preview_text)
        self._set_bottom_row_dropdowns_enabled(True)

        # Keep the top control container always visible across modes
        try:
            self.top_control_container.setVisible(True)
        except Exception:
            pass

        if mode == 'write':
            self.include_prompt_checkbox.setVisible(True)
            self.include_prompt_checkbox.setText(_("Include Action Beats"))
            self.include_prompt_checkbox.setEnabled(True)
            self.include_prompt_checkbox.setToolTip(_("Include the text from the Action Beats field in the scene text"))
        elif mode == 'rewrite':
            # Hide the checkbox for since it doesn't apply
            self.include_prompt_checkbox.setVisible(False)
            # self.include_prompt_checkbox.setText(_("Include Selected Text"))
            self.include_prompt_checkbox.setEnabled(False)
            # self.include_prompt_checkbox.setToolTip(_("Include the original selection when applying the preview"))
        elif mode == 'summarize':
            # self.include_prompt_checkbox.setText(_("Include Action Beats"))
            self.include_prompt_checkbox.setVisible(False)
            self.include_prompt_checkbox.setEnabled(False)
            # self.include_prompt_checkbox.setToolTip(_("Select a prompt tab to enable this option"))
        else:  # chapter mode
            self.include_prompt_checkbox.setText(_("Include Action Beats"))
            self.include_prompt_checkbox.setEnabled(False)
            self.include_prompt_checkbox.setToolTip(_("Not applicable on chapter panel"))

        if is_prompt_mode:
            self._ensure_state_initialized(mode)
            self._update_custom_edits_indicator()
        else:
            self.custom_edits_label.setVisible(False)

        # Update send button enabled state immediately when changing tabs
        try:
            if hasattr(self, 'send_button') and self.send_button:
                if mode == 'rewrite':
                    has_text = False
                    try:
                        has_text = bool(self.rewrite_tab.get_selected_text())
                    except Exception:
                        has_text = False
                    self.send_button.setEnabled(has_text)
                elif mode == 'write':
                    has_beats = False
                    try:
                        has_beats = bool(getattr(self, 'prompt_input') and self.prompt_input.toPlainText().strip())
                    except Exception:
                        has_beats = False
                    self.send_button.setEnabled(has_beats)
                else:
                    # Summarize and others: enable by default
                    self.send_button.setEnabled(True)
        except Exception:
            pass

    def _on_editor_selection_changed(self):
        # Always update the rewrite tab's selected-text box when the editor selection changes.
        if not hasattr(self, 'prompt_tab_widget') or not hasattr(self, 'rewrite_tab'):
            return

        selected_text = ""
        try:
            cursor = self.scene_editor.editor.textCursor()
            if cursor and cursor.hasSelection():
                fragment = cursor.selection()
                selected_text = fragment.toPlainText()
        except Exception:
            pass

        # Populate the rewrite tab's selection area with the latest selection (or clear it).
        try:
            if self.rewrite_tab:
                if selected_text:
                    self.rewrite_tab.set_selected_text(selected_text)
                else:
                    self.rewrite_tab.clear_selected_text()
        except Exception:
            pass

        # Do NOT disable/grey out the rewrite tab anymore; the tab remains selectable.

        # If the user is currently on the Rewrite tab, ensure the text box shows the latest selection.
        if self.active_mode == 'rewrite' and hasattr(self, 'rewrite_tab') and self.rewrite_tab:
            try:
                # Force a UI refresh if the rewrite tab has a method for it
                if hasattr(self.rewrite_tab, 'refresh_display'):
                    self.rewrite_tab.refresh_display()
            except Exception:
                pass

        # Update send button enabled state based on current active tab input content
        try:
            if self.active_mode == 'rewrite':
                # disable send when rewrite selection box is empty
                text_present = False
                try:
                    text_present = bool(self.rewrite_tab.get_selected_text())
                except Exception:
                    text_present = False
                if hasattr(self, 'send_button') and self.send_button:
                    self.send_button.setEnabled(text_present)
            elif self.active_mode == 'write':
                # disable send when action beats (prompt_input) is empty
                beats_present = False
                try:
                    beats_present = bool(getattr(self, 'prompt_input') and self.prompt_input.toPlainText().strip())
                except Exception:
                    beats_present = False
                if hasattr(self, 'send_button') and self.send_button:
                    self.send_button.setEnabled(beats_present)
            else:
                # other modes: enable send button if present
                if hasattr(self, 'send_button') and self.send_button:
                    self.send_button.setEnabled(True)
        except Exception:
            pass

    def _on_prompt_input_changed(self):
        """Called when the Beats prompt_input changes; update send button immediately."""
        try:
            if getattr(self, 'active_mode', '') != 'write':
                return
            has_beats = False
            try:
                has_beats = bool(getattr(self, 'prompt_input') and self.prompt_input.toPlainText().strip())
            except Exception:
                has_beats = False
            if hasattr(self, 'send_button') and self.send_button:
                self.send_button.setEnabled(has_beats)
        except Exception:
            pass
            
    def on_prompt_selected(self, mode='write'):
        """Called when user selects a prompt from the dropdown for the given mode."""
        self.reset_temporary_config(mode)
        if mode == self.active_mode:
            self.custom_edits_label.setVisible(False)
    
    def reset_temporary_config(self, mode=None):
        """Reset the temporary config to match the currently selected prompt for a mode."""
        mode = mode or self.active_mode
        state = self.prompt_modes.get(mode)
        if not state:
            return

        self._suspend_temp_sync = True
        panel = state['prompt_panel']
        state['original_prompt_config'] = panel.get_prompt()

        if not state['original_prompt_config'] or not state['original_prompt_config'].get("messages"):
            state['temporary_prompt_config'] = None
            state['has_custom_edits'] = False
            state['initialized'] = True
            if mode == self.active_mode:
                self.custom_edits_label.setVisible(False)
            self._suspend_temp_sync = False
            return

        state['temporary_prompt_config'] = deepcopy(state['original_prompt_config'])
        state['has_custom_edits'] = False
        state['initialized'] = True

        if hasattr(self, 'tweaks_widget'):
            self.tweaks_widget.clear_tweaks()

        if hasattr(self, 'preview_editable_widget'):
            self.preview_editable_widget.set_prompt_config(state['temporary_prompt_config'])

        if mode == self.active_mode:
            self.custom_edits_label.setVisible(False)

        self._suspend_temp_sync = False
    
    def on_temp_config_edited(self):
        """Called when user makes changes to tweaks or editable preview."""
        if self._suspend_temp_sync:
            return

        state = self._get_state()
        if not state:
            return

        if not state['has_custom_edits']:
            state['has_custom_edits'] = True
            if self.active_mode in self.prompt_modes:
                self.custom_edits_label.setVisible(True)
        
        # Note: We'll get the edited config from the widget when we need it
        # (when toggling preview or sending), not on every edit signal
        # This avoids unnecessary updates during typing
        self._sync_editable_prompt_changes()

    def _sync_editable_prompt_changes(self):
        """Persist editable prompt changes into the temporary config immediately."""
        if self._suspend_temp_sync:
            return

        state = self._get_state()
        if not state:
            return

        if not hasattr(self, 'preview_editable_widget') or not self.preview_editable_widget:
            return

        try:
            edited_config = self.preview_editable_widget.get_edited_config()
        except Exception:
            return

        if not edited_config:
            return

        state['temporary_prompt_config'] = edited_config
    
    def toggle_tweak_prompt(self):
        """Toggle the tweak prompt tabbed widget."""
        state = self._get_state()
        if not state:
            self.tweak_prompt_button.setChecked(False)
            return

        if self.tweak_prompt_button.isChecked():
            self.custom_edits_label.setVisible(True)
            if not state['temporary_prompt_config']:
                self.reset_temporary_config(self.active_mode)

            if not state['temporary_prompt_config']:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, _("No Prompt Selected"), 
                                  _("Please select a prompt first."))
                self.tweak_prompt_button.setChecked(False)
                return
            
            self.preview_editable_widget.set_prompt_config(state['temporary_prompt_config'])

            # Show the tweaks widget
            self.preview_button.setChecked(False)
            self._set_bottom_row_dropdowns_enabled(True)
            self.preview_stack.setCurrentWidget(self.tweaks_widget)
        else:
            # Hide and return to default view
            self.preview_stack.setCurrentWidget(self.preview_text)

    def toggle_edit_prompt(self):
        """Toggle the editable prompt view (separate from tweaks)."""
        state = self._get_state()
        if not state:
            try:
                if hasattr(self, 'edit_prompt_button'):
                    self.edit_prompt_button.setChecked(False)
            except Exception:
                pass
            return

        if getattr(self, 'edit_prompt_button', None) and self.edit_prompt_button.isChecked():
            # Show editable prompt view
            if not state['temporary_prompt_config']:
                self.reset_temporary_config(self.active_mode)

            if not state['temporary_prompt_config']:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, _("No Prompt Selected"), 
                                  _("Please select a prompt first."))
                self.edit_prompt_button.setChecked(False)
                return

            self.preview_editable_widget.set_prompt_config(state['temporary_prompt_config'])
            self.preview_stack.setCurrentWidget(self.preview_editable_widget)
        else:
            self.preview_stack.setCurrentWidget(self.preview_text)

    def update_send_button_state(self):
        """Enable/disable send button based on active mode required input presence."""
        try:
            if not hasattr(self, 'send_button') or not self.send_button:
                return

            if self.active_mode == 'rewrite':
                text_present = False
                try:
                    text_present = bool(self.rewrite_tab.get_selected_text())
                except Exception:
                    text_present = False
                self.send_button.setEnabled(text_present)
            elif self.active_mode == 'write':
                beats_present = False
                try:
                    beats_present = bool(getattr(self, 'prompt_input') and self.prompt_input.toPlainText().strip())
                except Exception:
                    beats_present = False
                self.send_button.setEnabled(beats_present)
            else:
                # Other modes allow send by default
                self.send_button.setEnabled(True)
        except Exception:
            pass
    
    def toggle_preview(self):
        """Toggle the uneditable preview widget."""
        state = self._get_state()
        if not state:
            self.preview_button.setChecked(False)
            self.preview_stack.setCurrentWidget(self.preview_text)
            return

        if self.preview_button.isChecked():
            # Show uneditable preview
            # Hide tweak widget if showing
            self.tweak_prompt_button.setChecked(False)
            
            # Get the config to use - if we have custom edits, get latest from editable widget
            if state['has_custom_edits']:
                edited_config = self.preview_editable_widget.get_edited_config()
                if edited_config:
                    state['temporary_prompt_config'] = edited_config
                config_to_use = state['temporary_prompt_config']
            else:
                config_to_use = state['prompt_panel'].get_prompt()
            
            # Validate we have a config
            if not config_to_use or not config_to_use.get("messages"):
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, _("No Prompt Selected"), 
                                  _("Please select a prompt first."))
                self.preview_button.setChecked(False)
                self._set_bottom_row_dropdowns_enabled(True)
                return
            
            # Assemble and show final prompt
            user_input = self._get_user_input_for_mode(self.active_mode)
            additional_vars = self.get_additional_vars()
            
            self.preview_uneditable_widget.set_prompt_data(
                prompt_config=config_to_use,
                user_input=user_input,
                additional_vars=additional_vars,
                current_scene_text=self.scene_editor.editor.toPlainText(),
                extra_context=None
            )
            
            self._set_bottom_row_dropdowns_enabled(False)

            self.preview_stack.setCurrentWidget(self.preview_uneditable_widget)
        else:
            # Hide and return to default view
            self._set_bottom_row_dropdowns_enabled(True)
            self.preview_stack.setCurrentWidget(self.preview_text)
    
    def refresh_prompt(self):
        """Refresh prompt and discard all custom edits."""
        self.reset_temporary_config()
        state = self._get_state()
        if state:
            state['has_custom_edits'] = False
        self.custom_edits_label.setVisible(False)
        
        # Also hide any special views and return to default
        self.tweak_prompt_button.setChecked(False)
        self.preview_button.setChecked(False)
        self._set_bottom_row_dropdowns_enabled(True)
        self.preview_stack.setCurrentWidget(self.preview_text)
    
    def send_prompt_with_temp_config(self):
        """Send prompt using temporary config if it has custom edits."""
        # Always show the LLM output preview before sending
        if self.preview_button.isChecked():
            self.preview_button.setChecked(False)
        if self.tweak_prompt_button.isChecked():
            self.tweak_prompt_button.setChecked(False)
        self.preview_stack.setCurrentWidget(self.preview_text)
        self._set_bottom_row_dropdowns_enabled(True)

        state = self._get_state()
        if state and state['has_custom_edits'] and state['temporary_prompt_config']:
            edited_config = self.preview_editable_widget.get_edited_config()
            if edited_config:
                state['temporary_prompt_config'] = edited_config

        self.controller.send_prompt()
    
    def _generate_chapter_summaries(self):
        """Generate summaries for scenes in the current chapter."""
        if not hasattr(self, 'chapter_summary_panel'):
            return
        
        current_item = self.project_tree.tree.currentItem()
        if not current_item:
            return
        
        level = self.project_tree.get_item_level(current_item)
        if level != 1:  # Must be a chapter
            return
        
        # Get prompt configuration
        prompt_config = self.chapter_summary_panel.prompt_panel.get_prompt()
        if not prompt_config or not prompt_config.get("name"):
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, _("No Prompt"), _("Please select a summary prompt."))
            return
        
        overwrite = self.chapter_summary_panel.overwrite_checkbox.isChecked()
        
        # Collect scenes to summarize
        scenes_to_summarize = []
        for i in range(current_item.childCount()):
            scene_item = current_item.child(i)
            hierarchy = self.controller.get_item_hierarchy(scene_item)
            node = self.model._get_node_by_hierarchy(hierarchy)
            
            if node:
                # Check if we should process this scene
                if overwrite or not node.get("summary", "").strip():
                    scenes_to_summarize.append({
                        'item': scene_item,
                        'hierarchy': hierarchy,
                        'node': node
                    })
        
        if not scenes_to_summarize:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, _("No Scenes"), _("All scenes already have summaries. Check 'Overwrite Existing Scene Summaries' to regenerate."))
            return
        
        # Start generation process
        self._start_batch_summary_generation(scenes_to_summarize, prompt_config)
    
    def _start_batch_summary_generation(self, scenes, prompt_config):
        """Start generating summaries for multiple scenes."""
        from settings.llm_worker import LLMWorker
        from muse.jinja_renderer import render_prompt
        
        if not scenes:
            return
        
        # Store state for batch processing
        self._batch_scenes = scenes
        self._batch_current_index = 0
        self._batch_prompt_config = prompt_config
        self._batch_worker = None
        
        # Process first scene
        self._process_next_batch_scene()
    
    def _process_next_batch_scene(self):
        """Process the next scene in the batch."""
        if self._batch_current_index >= len(self._batch_scenes):
            # All done
            self._batch_scenes = []
            self._batch_current_index = 0
            self._batch_prompt_config = None
            if self._batch_worker:
                self._batch_worker = None
            
            # Refresh the chapter summary display
            self.controller.load_current_item_content()
            return
        
        from settings.llm_worker import LLMWorker
        from muse.jinja_renderer import render_prompt
        from muse.prompt_variables import get_prompt_variables
        
        scene_data = self._batch_scenes[self._batch_current_index]
        hierarchy = scene_data['hierarchy']
        node = scene_data['node']
        
        # Load scene content
        content = self.model.load_scene_content(hierarchy)
        if not content:
            # Skip this scene and move to next
            self._batch_current_index += 1
            self._process_next_batch_scene()
            return
        
        # Get POV/tense from scene node
        pov = node.get("pov", "Third Person")
        pov_character = node.get("pov_character", "")
        tense = node.get("tense", "Past Tense")
        
        # Build variables for this scene
        variables = {
            'pov': pov,
            'pov_character': pov_character,
            'tense': tense,
            'scene': {
                'fullText': content
            }
        }
        
        # Render prompt
        try:
            final_prompt = render_prompt(self._batch_prompt_config.get('text', ''), variables)
        except Exception as e:
            print(f"Error rendering prompt for scene {hierarchy}: {e}")
            self._batch_current_index += 1
            self._process_next_batch_scene()
            return
        
        # Create worker
        overrides = {
            "provider": self._batch_prompt_config.get("provider", ""),
            "model": self._batch_prompt_config.get("model", ""),
            "max_tokens": self._batch_prompt_config.get("max_tokens", 2000),
            "temperature": self._batch_prompt_config.get("temperature", 1.0),
        }
        
        self._batch_worker = LLMWorker(final_prompt, overrides)
        self._batch_worker.data_received.connect(lambda text: self._on_batch_scene_summary_received(text, scene_data))
        self._batch_worker.finished.connect(self._on_batch_scene_finished)
        self._batch_worker.start()
    
    def _on_batch_scene_summary_received(self, text, scene_data):
        """Handle summary text received for a scene."""
        node = scene_data['node']
        if 'summary' not in node:
            node['summary'] = ""
        node['summary'] += text
    
    def _on_batch_scene_finished(self):
        """Handle completion of one scene summary."""
        # Save the summary
        if self._batch_current_index < len(self._batch_scenes):
            scene_data = self._batch_scenes[self._batch_current_index]
            self.model.save_structure()
        
        # Move to next scene
        self._batch_current_index += 1
        self._process_next_batch_scene()
    
    def _stop_chapter_summary_generation(self):
        """Stop the batch summary generation."""
        if hasattr(self, '_batch_worker') and self._batch_worker:
            if self._batch_worker.isRunning():
                self._batch_worker.terminate()
                self._batch_worker.wait()
            self._batch_worker = None
        
        self._batch_scenes = []
        self._batch_current_index = 0
        self._batch_prompt_config = None
    
    def _preview_chapter_summary_prompt(self):
        """Preview the prompt that will be used for scene summaries."""
        # TODO: Implement preview functionality
        pass
    
    def _refresh_chapter_summary_prompt(self):
        """Refresh the prompt selection."""
        if hasattr(self, 'chapter_summary_panel'):
            self.chapter_summary_panel.prompt_panel.reload_prompts()