from PyQt5.QtWidgets import QToolBar, QAction, QWidget, QVBoxLayout
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt
from settings.theme_manager import ThemeManager

# gettext '_' fallback for static analysis / standalone edits
import builtins
if not hasattr(builtins, '_'):
    def _(text):
        return text
    builtins._ = _

class ActivityBar(QWidget):
    """Vertical icon panel for switching between views, similar to VS Code Activity Bar."""
    def __init__(self, controller, tint_color=QColor("black"), position="left"):
        super().__init__()
        self.controller = controller  # Reference to ProjectWindow
        self.tint_color = tint_color
        self.position = position  # 'left' or 'right' for future feature
        self.current_view = None
        self.toolbar = QToolBar("Activity Bar")
        self.toolbar.setObjectName("ActivityBar")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(self.toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar.setOrientation(Qt.Vertical)
        self.toolbar.setFixedWidth(50)  # Fixed width for icons

        # Actions - only 3 main views
        self.outline_editor_action = self.add_action(
            "assets/icons/pen-tool.svg",
            _("Outline & Scene Editor"),
            self.controller.switch_to_outline_editor
        )
        self.compendium_action = self.add_action(
            "assets/icons/book-open.svg",
            _("Compendium"),
            self.controller.switch_to_compendium
        )
        self.prompts_action = self.add_action(
            "assets/icons/ai-script-icon.svg",
            _("Prompt Options"),
            self.controller.switch_to_prompts
        )

        # Set initial state
        self.outline_editor_action.setChecked(True)
        self.current_view = "outline_editor"

        self._apply_highlight_style()

    def add_action(self, icon_path, tooltip, callback):
        action = QAction(ThemeManager.get_tinted_icon(icon_path, self.tint_color), "", self)
        action.setToolTip(tooltip)
        action.setCheckable(True)
        action.triggered.connect(lambda: self.handle_action(action, callback))
        self.toolbar.addAction(action)
        return action

    def handle_action(self, action, callback):
        """Handle action clicks, ensuring only one is checked."""
        if hasattr(self.controller, 'clear_search_highlights'):
            self.controller.clear_search_highlights()  # Clear search highlights
        
        # Always keep one view active
        if action.isChecked():
            # Uncheck other actions
            for act in [self.outline_editor_action, self.compendium_action, self.prompts_action]:
                if act != action:
                    act.setChecked(False)
            # Set current view
            view_map = {
                self.outline_editor_action: "outline_editor",
                self.compendium_action: "compendium",
                self.prompts_action: "prompts"
            }
            self.current_view = view_map.get(action)
            callback()  # Switch to the view
        else:
            # Don't allow unchecking - always need one view active
            action.setChecked(True)

    def update_tint(self, tint_color):
        """Update icon tints when theme changes."""
        self.tint_color = tint_color
        self.outline_editor_action.setIcon(ThemeManager.get_tinted_icon("assets/icons/pen-tool.svg", tint_color))
        self.compendium_action.setIcon(ThemeManager.get_tinted_icon("assets/icons/book-open.svg", tint_color))
        self.prompts_action.setIcon(ThemeManager.get_tinted_icon("assets/icons/ai-script-icon.svg", tint_color))
        self._apply_highlight_style()

    def _apply_highlight_style(self):
        highlight_color = ThemeManager.get_toggle_highlight_color()
        base_style = "QToolBar#ActivityBar { border: 0px; }"

        if not highlight_color:
            self.toolbar.setStyleSheet(base_style)
            return

        rgba = f"rgba({highlight_color.red()}, {highlight_color.green()}, {highlight_color.blue()}, {highlight_color.alpha()})"
        checked_style = f"QToolBar#ActivityBar QToolButton:checked {{ background-color: {rgba}; border-radius: 6px; }}"
        self.toolbar.setStyleSheet("\n".join([base_style, checked_style]))