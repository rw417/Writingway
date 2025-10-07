"""
Outline & Scene Editor Widget - Combined view for project navigation, search, editing, and LLM controls.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget)
from PyQt5.QtCore import Qt
from .project_tree_widget import ProjectTreeWidget
from .search_replace_panel import SearchReplacePanel
from .scene_editor import SceneEditor
from .bottom_stack import BottomStack

# gettext '_' fallback for static analysis / standalone edits
import builtins
if not hasattr(builtins, '_'):
    def _(text):
        return text
    builtins._ = _


class OutlineSceneEditorWidget(QWidget):
    """
    A composite widget containing:
    - Left side: Tabbed panel with Outline and Search & Replace
    - Right side: Scene editor and Bottom stack (LLM controls)
    
    This encapsulates the complete scene editing workflow.
    """
    
    def __init__(self, project_window, model, icon_tint, parent=None):
        super().__init__(parent)
        self.project_window = project_window
        self.model = model
        self.icon_tint = icon_tint
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI layout."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Main horizontal splitter
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)
        
        # Left side: Tabbed widget with Outline and Search
        self.left_tabs = QTabWidget()
        self.left_tabs.setMinimumWidth(200)
        
        # Create project tree (Outline)
        self.project_tree = ProjectTreeWidget(self.project_window, self.model)
        self.left_tabs.addTab(self.project_tree, _("Outline"))
        
        # Create scene editor first (search panel needs it)
        self.scene_editor = SceneEditor(self.project_window, self.icon_tint)
        
        # Temporarily set references on project_window so other components can access them
        self.project_window.scene_editor = self.scene_editor
        self.project_window.project_tree = self.project_tree
        
        # Now create search panel
        self.search_panel = SearchReplacePanel(self.project_window, self.model, self.icon_tint)
        self.left_tabs.addTab(self.search_panel, _("Search & Replace"))
        
        self.main_splitter.addWidget(self.left_tabs)
        
        # Right side: Scene editor and bottom stack
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(self.scene_editor)
        
        # Bottom stack (LLM controls)
        self.bottom_stack = BottomStack(self.project_window, self.model, self.icon_tint)
        right_splitter.addWidget(self.bottom_stack)
        
        # Set stretch factors
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 1)
        
        self.main_splitter.addWidget(right_splitter)
        
        # Set stretch factors for main splitter
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setHandleWidth(10)
    
    def update_tint(self, icon_tint):
        """Update icon tint for all child widgets."""
        self.icon_tint = icon_tint
        self.scene_editor.update_tint(icon_tint)
        self.bottom_stack.update_tint(icon_tint)
        self.search_panel.update_tint(icon_tint)
        self.project_tree.assign_all_icons()
