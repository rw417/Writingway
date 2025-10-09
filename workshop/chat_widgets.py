from __future__ import annotations

from typing import Dict, Iterable, Optional
import html
import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPaintEvent
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from .chat_models import ChatMessage
from settings.theme_manager import ThemeManager


class ChatBubbleWidget(QWidget):
    request_swipe = pyqtSignal(str)
    request_branch = pyqtSignal(str)
    request_prev_variant = pyqtSignal(str)
    request_next_variant = pyqtSignal(str)

    def __init__(self, message: ChatMessage, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._message_id = message.id
        self._role = message.role
        self._message = message
        self._build_ui()
        self.bind_message(message)

    def _build_ui(self):
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(12, 6, 12, 6)

        if self._role == "user":
            self.main_layout.addStretch()

        container = QVBoxLayout()
        container.setSpacing(4)

        # Use a custom frame that paints a rounded bubble to avoid stylesheet conflicts
        class ChatBubbleFrame(QFrame):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._bg_color = QColor("#ffffff")
                self._radius = 12

            def set_bg_color(self, color: str):
                self._bg_color = QColor(color)
                self.update()

            def set_radius(self, radius: int):
                self._radius = radius
                self.update()

            def paintEvent(self, event: QPaintEvent):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._bg_color)
                rect = self.rect()
                painter.drawRoundedRect(rect, self._radius, self._radius)

        bubble_frame = ChatBubbleFrame()
        bubble_frame.setObjectName("chatBubble")
        bubble_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        bubble_frame_layout = QVBoxLayout(bubble_frame)
        bubble_frame_layout.setContentsMargins(14, 10, 14, 10)

        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        self.content_label.setTextFormat(Qt.RichText)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        bubble_frame_layout.addWidget(self.content_label)

        container.addWidget(bubble_frame)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(6)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        self.prev_button = QPushButton()
        self.prev_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/chevron-left.svg"))
        self.prev_button.setToolTip("Previous response variant")
        self.prev_button.clicked.connect(lambda: self.request_prev_variant.emit(self._message_id))
        controls_layout.addWidget(self.prev_button)

        self.swipe_button = QPushButton()
        self.swipe_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/refresh-cw.svg"))
        self.swipe_button.setToolTip("Regenerate response")
        self.swipe_button.clicked.connect(lambda: self.request_swipe.emit(self._message_id))
        controls_layout.addWidget(self.swipe_button)

        self.next_button = QPushButton()
        self.next_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/chevron-right.svg"))
        self.next_button.setToolTip("Next response variant")
        self.next_button.clicked.connect(lambda: self.request_next_variant.emit(self._message_id))
        controls_layout.addWidget(self.next_button)

        controls_layout.addSpacerItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.branch_button = QPushButton()
        self.branch_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/git-branch.svg"))
        self.branch_button.setToolTip("Branch conversation from this message")
        self.branch_button.clicked.connect(lambda: self.request_branch.emit(self._message_id))
        controls_layout.addWidget(self.branch_button)

        container.addLayout(controls_layout)

        if self._role == "assistant":
            self.main_layout.addLayout(container)
            self.main_layout.addStretch()
        else:
            self.main_layout.addLayout(container)

        self._bubble_frame = bubble_frame
        self._controls_layout = controls_layout
        self._controls_container = container
        self._bubble_width_ratio = 0.9

        self._apply_styles()
        self._update_bubble_width()

    def _apply_styles(self):
        palette = self.palette()
        base_color = palette.color(self.backgroundRole())
        text_color = palette.color(self.foregroundRole()).name()
        # Use explicit contrasting colors so bubbles are always visibly shaded
        # Assistant: very light gray; User: light blue-gray
        if self._role == "user":
            bubble_color = "#b0c8ee"  # light blue for user messages
            label_color = "#001522"   # dark text for contrast
        else:
            bubble_color = "#D1D2D3"  # light gray for assistant messages
            label_color = "#0b1b2b"   # dark text for contrast
        border_radius = "16px"

        # Apply the background via the custom painted frame and keep label transparent
        if hasattr(self, "_bubble_frame") and self._bubble_frame is not None:
            # radius as integer
            try:
                radius_int = int(border_radius.replace("px", ""))
            except Exception:
                radius_int = 12
            # flush to the custom frame painter
            if hasattr(self._bubble_frame, "set_bg_color"):
                self._bubble_frame.set_bg_color(bubble_color)
                self._bubble_frame.set_radius(radius_int)
            else:
                # fallback to stylesheet
                self._bubble_frame.setStyleSheet(
                    f"background-color: {bubble_color}; border: none; border-radius: {border_radius};"
                )
            # Ensure the label text is visible and its background stays transparent
            self.content_label.setStyleSheet(f"color: {label_color}; background: transparent;")
        else:
            # Fallback: apply to this widget (shouldn't normally happen)
            self.setStyleSheet(
                f"QFrame#chatBubble {{ background-color: {bubble_color}; border: none; border-radius: {border_radius}; }}"
            )
        self.content_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.main_layout.setAlignment(Qt.AlignRight if self._role == "user" else Qt.AlignLeft)

        is_assistant = self._role == "assistant"
        self.prev_button.setVisible(is_assistant)
        self.next_button.setVisible(is_assistant)
        self.swipe_button.setVisible(is_assistant)
        self.branch_button.setVisible(True)

    def bind_message(self, message: ChatMessage):
        self._message = message
        self._role = message.role
        content = self._render_html(message.content)
        self.content_label.setText(content)
        self._apply_styles()
        self._update_bubble_width()
        self.update_variant_controls()

    def update_variant_controls(self):
        if self._role != "assistant":
            self.prev_button.setVisible(False)
            self.next_button.setVisible(False)
            self.swipe_button.setVisible(False)
            return

        total = len(self._message.variants)
        self.prev_button.setEnabled(self._message.active_index > 0)
        self.next_button.setEnabled(self._message.active_index < total - 1)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        branch_action = menu.addAction("Branch from here")
        action = menu.exec_(event.globalPos())
        if action == branch_action:
            self.request_branch.emit(self._message_id)

    def _render_html(self, text: str) -> str:
        if not text:
            return "&nbsp;"

        escaped = html.escape(text)
        escaped = escaped.replace("\n", "<br/>")
        bolded = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        italicized = re.sub(r"\*(.+?)\*", r"<i>\1</i>", bolded)
        return italicized

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_bubble_width()

    def _update_bubble_width(self):
        if not hasattr(self, "_bubble_frame"):
            return
        available_width = max(self.width(), 0)
        if available_width <= 0:
            return
        target_width = int(available_width * self._bubble_width_ratio)
        if target_width <= 0:
            target_width = available_width
        self._bubble_frame.setMaximumWidth(target_width)
        self._bubble_frame.setMinimumWidth(min(target_width, available_width))
        self._bubble_frame.updateGeometry()


class ChatListWidget(QListWidget):
    message_selected = pyqtSignal(str)
    swipe_requested = pyqtSignal(str)
    prev_variant_requested = pyqtSignal(str)
    next_variant_requested = pyqtSignal(str)
    branch_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SingleSelection)
        self._items: Dict[str, QListWidgetItem] = {}
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.setSpacing(4)
        self.setAlternatingRowColors(False)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)

    def _on_selection_changed(self):
        selected = self.selectedItems()
        if not selected:
            return
        item = selected[0]
        message_id = item.data(Qt.UserRole)
        if message_id:
            self.message_selected.emit(message_id)

    def add_or_update_message(self, message: ChatMessage, *, select: bool = False):
        item = self._items.get(message.id)
        if item is None:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, message.id)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            widget = ChatBubbleWidget(message)
            widget.request_swipe.connect(self._emit_swipe)
            widget.request_prev_variant.connect(self._emit_prev_variant)
            widget.request_next_variant.connect(self._emit_next_variant)
            widget.request_branch.connect(self._emit_branch)
            item.setSizeHint(widget.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, widget)
            self._items[message.id] = item
        else:
            widget = self.itemWidget(item)
            if isinstance(widget, ChatBubbleWidget):
                widget.bind_message(message)
                item.setSizeHint(widget.sizeHint())
        if select:
            self.setCurrentItem(item)
        self.scrollToBottom()

    def remove_message(self, message_id: str):
        item = self._items.pop(message_id, None)
        if item is None:
            return
        row = self.row(item)
        self.takeItem(row)

    def clear_messages(self):
        super().clear()
        self._items.clear()

    def _emit_swipe(self, message_id: str):
        self.swipe_requested.emit(message_id)

    def _emit_prev_variant(self, message_id: str):
        self.prev_variant_requested.emit(message_id)

    def _emit_next_variant(self, message_id: str):
        self.next_variant_requested.emit(message_id)

    def _emit_branch(self, message_id: str):
        self.branch_requested.emit(message_id)

    def populate(self, messages: Iterable[ChatMessage]):
        self.clear_messages()
        for message in messages:
            self.add_or_update_message(message)
        self.scrollToBottom()
