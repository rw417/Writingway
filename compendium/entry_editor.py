from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QFormLayout, QLineEdit, QCheckBox, QTabWidget, QGroupBox, QScrollArea, QListWidget, QTreeWidget, QComboBox
import os
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont, QPixmap

class EntryEditor(QWidget):
    """Encapsulates the center panel (entry editor) UI.

    Exposes essential widgets and a small API so the main window can continue
    using existing handlers with minimal changes.
    """

    entry_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # Header
        self.header_widget = QWidget()
        header_layout = QHBoxLayout(self.header_widget)
        self.entry_name_label = QLabel("No entry selected")
        self.entry_name_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        header_layout.addWidget(self.entry_name_label)
        header_layout.addStretch()
        self.save_button = QPushButton("Save Changes")
        header_layout.addWidget(self.save_button)
        layout.addWidget(self.header_widget)

        # Metadata
        self.metadata_widget = QWidget()
        metadata_layout = QFormLayout(self.metadata_widget)
        self.alias_line_edit = QLineEdit()
        self.alias_line_edit.setPlaceholderText("Aliases (comma-separated)")
        metadata_layout.addRow("Aliases:", self.alias_line_edit)
        self.track_checkbox = QCheckBox("Track by name")
        self.track_checkbox.setChecked(True)
        metadata_layout.addRow("", self.track_checkbox)
        layout.addWidget(self.metadata_widget)

        # Tabs
        self.tabs = QTabWidget()
        self.overview_tab = QWidget()
        overview_layout = QVBoxLayout(self.overview_tab)
        self.description_label = QLabel("Description")
        overview_layout.addWidget(self.description_label)
        self.editor = QTextEdit()
        overview_layout.addWidget(self.editor)
        self.tabs.addTab(self.overview_tab, "Overview")

        # Details tab
        self.details_editor = QTextEdit()
        self.tabs.addTab(self.details_editor, "Details")

        # Relationships tab
        # Add relationship controls (entry chooser, type chooser, add button)
        self.relationships_tab = QWidget()
        relationships_layout = QVBoxLayout(self.relationships_tab)
        add_rel_group = QGroupBox("Add Relationship")
        add_rel_layout = QFormLayout(add_rel_group)
        self.rel_entry_combo = QComboBox()
        self.rel_type_combo = QComboBox()
        self.rel_type_combo.addItems(["Friend", "Family", "Ally", "Enemy", "Acquaintance", "Other"])
        self.rel_type_combo.setEditable(True)
        self.add_rel_button = QPushButton("Add")
        add_rel_layout.addRow("Related Entry:", self.rel_entry_combo)
        add_rel_layout.addRow("Relationship Type:", self.rel_type_combo)
        add_rel_layout.addRow("", self.add_rel_button)
        relationships_layout.addWidget(add_rel_group)
        self.relationships_list = QTreeWidget()
        self.relationships_list.setHeaderLabels(["Entry", "Relationship Type"])
        self.relationships_list.setContextMenuPolicy(Qt.CustomContextMenu)
        # Allow multi-selection and add Ctrl+A
        try:
            from PyQt5.QtWidgets import QAbstractItemView, QShortcut
            from PyQt5.QtGui import QKeySequence
            self.relationships_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.relationships_list.setSelectionBehavior(QAbstractItemView.SelectRows)
            sc = QShortcut(QKeySequence("Ctrl+A"), self.relationships_list)
            sc.activated.connect(lambda: self._select_all_in_tree(self.relationships_list))
        except Exception:
            pass
        relationships_layout.addWidget(self.relationships_list)
        self.tabs.addTab(self.relationships_tab, "Relationships")

        # Images tab
        images_layout = QVBoxLayout()
        image_controls = QWidget()
        image_controls_layout = QHBoxLayout(image_controls)
        self.add_image_button = QPushButton("Add Image")
        self.remove_image_button = QPushButton("Remove Selected")
        self.remove_image_button.setEnabled(False)
        image_controls_layout.addWidget(self.add_image_button)
        image_controls_layout.addWidget(self.remove_image_button)
        image_controls_layout.addStretch()
        images_layout.addWidget(image_controls)

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_container = QWidget()
        self.image_layout = QVBoxLayout(self.image_container)
        self.image_scroll.setWidget(self.image_container)
        images_layout.addWidget(self.image_scroll)
        images_widget = QWidget()
        images_widget.setLayout(images_layout)
        self.tabs.addTab(images_widget, "Images")

        layout.addWidget(self.tabs)

    def set_entry_name(self, name: str):
        self.entry_name_label.setText(name)

    def clear(self):
        self.entry_name_label.setText("No entry selected")
        self.editor.clear()
        self.details_editor.clear()
        self.alias_line_edit.clear()
        self.track_checkbox.setChecked(True)
        self.tabs.hide()

    def _select_all_in_tree(self, tree_widget):
        try:
            root = tree_widget.invisibleRootItem()
            def recurse(parent):
                for i in range(parent.childCount()):
                    child = parent.child(i)
                    if not child.isHidden():
                        child.setSelected(True)
                    recurse(child)
            recurse(root)
        except Exception:
            pass

    # Minimal getter/setter for other code to remain compatible
    def get_description(self) -> str:
        return self.editor.toPlainText()

    def set_description(self, text: str) -> None:
        self.editor.setPlainText(text)

    def set_details(self, text: str) -> None:
        self.details_editor.setPlainText(text)

    def get_details(self) -> str:
        return self.details_editor.toPlainText()

    def add_image_widget(self, widget):
        self.image_layout.addWidget(widget)

    def clear_images(self):
        while self.image_layout.count():
            child = self.image_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        # clear selection state when images are cleared
        if hasattr(self, 'selected_image'):
            try:
                del self.selected_image
            except Exception:
                pass
        self.remove_image_button.setEnabled(False)

    # Image helpers moved here so the main window can delegate UI-only work.
    def add_image_from_path(self, image_path: str, filename: str) -> None:
        """Add an image widget to the images panel from an existing file path."""
        image_container = QWidget()
        image_layout = QVBoxLayout(image_container)
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            max_width = 400
            if pixmap.width() > max_width:
                pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)
            image_label = QLabel()
            image_label.setPixmap(pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setProperty("filename", filename)
            image_label.setFrameShape(QLabel.Box)
            image_label.setObjectName("image")
            # clicking an image selects it for removal
            image_label.mousePressEvent = lambda event, label=image_label: self.select_image(label)
            image_layout.addWidget(image_label)
            name_label = QLabel(filename)
            name_label.setAlignment(Qt.AlignCenter)
            image_layout.addWidget(name_label)
            self.image_layout.addWidget(image_container)
        else:
            # if pixmap failed to load, ignore silently (caller may log)
            return

    def load_images(self, image_filenames: list, images_dir: str) -> None:
        """Load multiple images from filenames using the provided images_dir."""
        self.clear_images()
        if not image_filenames:
            return
        for filename in image_filenames:
            image_path = os.path.join(images_dir, filename)
            if os.path.exists(image_path):
                self.add_image_from_path(image_path, filename)

    def select_image(self, label: QLabel) -> None:
        """Mark the provided QLabel as the selected image for removal."""
        # clear previous selection visual state
        for i in range(self.image_layout.count()):
            container = self.image_layout.itemAt(i).widget()
            if not container:
                continue
            for j in range(container.layout().count()):
                widget = container.layout().itemAt(j).widget()
                if isinstance(widget, QLabel) and widget.objectName() == "image":
                    widget.setStyleSheet("")
        label.setStyleSheet("border: 2px solid blue;")
        self.remove_image_button.setEnabled(True)
        self.selected_image = label
    def get_selected_image_filename(self):
        if not hasattr(self, 'selected_image') or self.selected_image is None:
            return None
        return self.selected_image.property("filename")

    def remove_selected_image_widget(self) -> None:
        """Remove the currently selected image widget from the UI."""
        if not hasattr(self, 'selected_image') or self.selected_image is None:
            return
        container = self.selected_image.parent()
        if container:
            container.deleteLater()
        try:
            del self.selected_image
        except Exception:
            pass
        self.remove_image_button.setEnabled(False)
    
    def show_tabs(self):
        self.tabs.show()

    def hide_tabs(self):
        self.tabs.hide()
