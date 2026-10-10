"""知识库数据结构。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Document:
    """待入库的原始文档。"""

    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    title: str = ""


@dataclass(slots=True)
class VectorRecord:
    """一条向量记录。"""

    id: str
    vector: list[float]
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievedChunk:
    """检索结果片段。"""

    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source(self) -> str:
        """来源标识，便于在回答中标注引用。"""

        return str(self.metadata.get("source", "") or self.metadata.get("title", ""))

    @property
    def subject(self) -> str:
        """所属科目。"""

        return str(self.metadata.get("subject", ""))

    def to_payload(self) -> dict[str, Any]:
        """转为可序列化结构。"""

        return {
            "id": self.id,
            "text": self.text,
            "score": round(self.score, 4),
            "source": self.source,
            "subject": self.subject,
            "metadata": self.metadata,
        }
