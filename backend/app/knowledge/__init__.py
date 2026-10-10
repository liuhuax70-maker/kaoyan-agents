"""知识库与检索增强（Milvus / 本地兜底）。"""

from app.knowledge.base import (
    KnowledgeBase,
    build_knowledge_base,
    get_knowledge_base,
    reset_knowledge_base,
    retrieve_context,
)
from app.knowledge.corpus import builtin_documents
from app.knowledge.embeddings import (
    BaseEmbedder,
    OpenAICompatEmbedder,
    StubEmbedder,
    build_embedder,
)
from app.knowledge.stores import (
    BaseVectorStore,
    LocalVectorStore,
    MilvusVectorStore,
    build_vector_store,
)
from app.knowledge.text import chunk_text, cosine_similarity, tokenize
from app.knowledge.types import Document, RetrievedChunk, VectorRecord

__all__ = [
    "BaseEmbedder",
    "BaseVectorStore",
    "Document",
    "KnowledgeBase",
    "LocalVectorStore",
    "MilvusVectorStore",
    "OpenAICompatEmbedder",
    "RetrievedChunk",
    "StubEmbedder",
    "VectorRecord",
    "build_embedder",
    "build_knowledge_base",
    "build_vector_store",
    "builtin_documents",
    "chunk_text",
    "cosine_similarity",
    "get_knowledge_base",
    "reset_knowledge_base",
    "retrieve_context",
    "tokenize",
]
