from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now_iso() -> str:
    return datetime.utcnow().strftime(ISO_FORMAT)


@dataclass
class ChatVariant:
    id: str
    content: str
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatVariant":
        return cls(
            id=data.get("id") or str(uuid.uuid4()),
            content=data.get("content", ""),
            created_at=data.get("created_at", _now_iso()),
        )


@dataclass
class ChatMessage:
    id: str
    role: str
    variants: List[ChatVariant] = field(default_factory=list)
    active_index: int = 0
    created_at: str = field(default_factory=_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.variants:
            self.variants = [ChatVariant(id=str(uuid.uuid4()), content="")]
        self.active_index = max(0, min(self.active_index, len(self.variants) - 1))

    @property
    def active_variant(self) -> ChatVariant:
        return self.variants[self.active_index]

    @property
    def content(self) -> str:
        return self.active_variant.content

    def set_content(self, value: str):
        self.variants[self.active_index].content = value

    def add_variant(self, content: str, *, set_active: bool = True) -> ChatVariant:
        variant = ChatVariant(id=str(uuid.uuid4()), content=content)
        self.variants.append(variant)
        if set_active:
            self.active_index = len(self.variants) - 1
        return variant

    def set_active_variant(self, variant_id: str) -> Optional[ChatVariant]:
        for index, variant in enumerate(self.variants):
            if variant.id == variant_id:
                self.active_index = index
                return variant
        return None

    def remove_variant(self, variant_id: str) -> bool:
        for index, variant in enumerate(self.variants):
            if variant.id == variant_id:
                self.variants.pop(index)
                if self.variants:
                    self.active_index = min(self.active_index, len(self.variants) - 1)
                else:
                    self.variants.append(ChatVariant(id=str(uuid.uuid4()), content=""))
                    self.active_index = 0
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "variants": [variant.to_dict() for variant in self.variants],
            "active_index": self.active_index,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        variants_data = data.get("variants") or []
        if not variants_data and "content" in data:
            variants_data = [{"content": data.get("content", ""), "id": data.get("variant_id") or str(uuid.uuid4())}]
        variants = [ChatVariant.from_dict(variant) for variant in variants_data]
        return cls(
            id=data.get("id") or str(uuid.uuid4()),
            role=data.get("role", "assistant"),
            variants=variants,
            active_index=data.get("active_index", 0),
            created_at=data.get("created_at", _now_iso()),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_legacy(cls, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> "ChatMessage":
        return cls(
            id=str(uuid.uuid4()),
            role=role,
            variants=[ChatVariant(id=str(uuid.uuid4()), content=content)],
            metadata=metadata or {},
        )


def serialize_messages(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
    return [message.to_dict() for message in messages]


def deserialize_messages(raw_messages: List[Dict[str, Any]]) -> List[ChatMessage]:
    messages: List[ChatMessage] = []
    for raw in raw_messages:
        if isinstance(raw, dict) and "variants" in raw:
            message = ChatMessage.from_dict(raw)
            if message.role == "user":
                message.metadata.setdefault("augmented_content", message.content)
                message.metadata.setdefault("overrides", {})
            messages.append(message)
        elif isinstance(raw, dict) and "role" in raw and "content" in raw:
            message = ChatMessage.from_legacy(raw.get("role", "assistant"), raw.get("content", ""))
            if message.role == "user":
                message.metadata.setdefault("augmented_content", message.content)
                message.metadata.setdefault("overrides", {})
            messages.append(message)
    return messages


def clone_history_until(messages: List[ChatMessage], message_id: str) -> List[ChatMessage]:
    cloned: List[ChatMessage] = []
    for message in messages:
        cloned.append(ChatMessage.from_dict(message.to_dict()))
        if message.id == message_id:
            break
    return cloned
