"""知识库与 RAG 检索测试：分词切片、向量化、向量库与检索增强。"""

import pytest

from app.core.config import Settings, get_settings
from app.knowledge import (
    Document,
    KnowledgeBase,
    LocalVectorStore,
    MilvusVectorStore,
    RetrievedChunk,
    build_vector_store,
    builtin_documents,
    chunk_text,
    cosine_similarity,
    reset_knowledge_base,
    retrieve_context,
    tokenize,
)
from app.prompts import render_retrieved
from tests.fakes import StubEmbedder


def _settings(dimension: int = 256, **knowledge: object) -> Settings:
    return Settings(
        embedding={"provider": "ollama", "dimension": dimension},
        knowledge={"chunk_size": 320, "chunk_overlap": 64, "top_k": 3, **knowledge},
    )


def _knowledge_base(tmp_path, dimension: int = 256) -> KnowledgeBase:
    return KnowledgeBase(
        store=LocalVectorStore("test_collection", tmp_path),
        embedder=StubEmbedder(dimension),
        settings=_settings(dimension),
    )


def test_tokenize_keeps_chinese_unigram_and_bigram() -> None:
    tokens = tokenize("数学 Math 极限")
    assert "数" in tokens
    assert "数学" in tokens
    assert "math" in tokens


def test_chunk_text_splits_long_text() -> None:
    text = "。".join(f"第{index}段内容用于测试切片逻辑" for index in range(60))
    chunks = chunk_text(text, size=120, overlap=30)

    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)
    assert all(len(chunk) <= 130 for chunk in chunks)


def test_chunk_text_keeps_short_text_intact() -> None:
    assert chunk_text("很短的文本", size=100) == ["很短的文本"]
    assert chunk_text("   ", size=100) == []


def test_cosine_similarity_handles_mismatched_length() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0
    assert cosine_similarity([], []) == 0.0


async def test_stub_embedder_is_deterministic_and_semantic() -> None:
    """测试用哈希向量必须稳定，且文本越接近相似度越高。"""

    embedder = StubEmbedder(512)
    math = await embedder.embed_one("数学要保证计算准确率，再追求解题速度")
    same = await embedder.embed_one("数学要保证计算准确率，再追求解题速度")
    other = await embedder.embed_one("英语真题按套限时训练，逐句翻译长难句")

    assert math == same
    assert len(math) == 512
    assert cosine_similarity(math, same) > cosine_similarity(math, other)


async def test_ingest_and_search_within_subject(tmp_path) -> None:
    base = _knowledge_base(tmp_path)
    written = await base.ingest(
        [
            Document(
                id="math-1",
                title="数学方法",
                text="数学的关键瓶颈通常不是不会做，而是算不对。应先保证准确率再追求速度。",
                metadata={"subject": "数学"},
            ),
            Document(
                id="english-1",
                title="英语方法",
                text="英语真题建议近十五年至少刷三遍，第一遍逐句翻译，第二遍限时训练。",
                metadata={"subject": "英语"},
            ),
        ]
    )
    assert written >= 2

    results = await base.search("数学计算准确率怎么提高", top_k=2)
    assert results
    assert results[0].subject == "数学"
    assert results[0].score > 0
    assert results[0].source == "数学方法"

    filtered = await base.search("数学计算准确率怎么提高", subject="英语")
    assert filtered == []


async def test_builtin_corpus_is_searchable(tmp_path) -> None:
    base = _knowledge_base(tmp_path, dimension=512)
    written = await base.ingest(builtin_documents())

    assert written >= len(builtin_documents())

    results = await base.search("英语真题要刷几遍，怎么刷", top_k=3)
    assert results
    assert any(item.subject == "英语" for item in results)

    stats = await base.stats()
    assert stats["chunks"] == written
    assert stats["backend"] == "LocalVectorStore"


async def test_ensure_builtin_corpus_is_idempotent(tmp_path) -> None:
    base = _knowledge_base(tmp_path)

    first = await base.ensure_builtin_corpus()
    second = await base.ensure_builtin_corpus()

    assert first > 0
    assert second == 0


async def test_upsert_overwrites_same_chunk_id(tmp_path) -> None:
    base = _knowledge_base(tmp_path)
    document = Document(id="dup", title="重复文档", text="第一版内容，用于验证覆盖写入。")

    await base.ingest([document])
    before = await base.count()
    await base.ingest([document])

    assert await base.count() == before


def test_vector_store_factory_selects_backend() -> None:
    local = build_vector_store(Settings(vector={"backend": "local"}))
    assert isinstance(local, LocalVectorStore)
    assert local.backend == "LocalVectorStore"

    milvus = build_vector_store(
        Settings(vector={"backend": "milvus", "milvus_uri": "http://localhost:19530"})
    )
    assert isinstance(milvus, MilvusVectorStore)
    assert milvus.backend == "MilvusVectorStore"


def test_render_retrieved_marks_sources() -> None:
    chunks = [
        RetrievedChunk(
            id="a",
            text="数学要保证计算准确率",
            score=0.876,
            metadata={"source": "数学复习方法", "subject": "数学"},
        )
    ]
    text = render_retrieved(chunks)

    assert "数学复习方法" in text
    assert "0.88" in text
    assert "数学要保证计算准确率" in text
    assert "未检索到参考资料" in render_retrieved([])


async def test_retrieve_context_degrades_on_configuration_error(monkeypatch) -> None:
    """向量化配置不可用时，检索应降级为空结果而不是抛错。"""

    monkeypatch.setenv("EMBEDDING__PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING__OPENAI_API_KEY", "")
    get_settings.cache_clear()
    reset_knowledge_base()

    try:
        assert await retrieve_context("任意问题") == []
    finally:
        reset_knowledge_base()
        get_settings.cache_clear()


async def test_retrieve_context_works_with_local_backend() -> None:
    reset_knowledge_base()
    chunks = await retrieve_context("英语真题怎么刷", top_k=3)

    assert chunks
    assert all(item.text for item in chunks)
    assert all(item.score >= 0 for item in chunks)


async def test_retrieve_context_can_be_disabled_per_request() -> None:
    """按请求显式关闭检索时应立即返回空结果，不受全局开关影响。"""

    reset_knowledge_base()

    assert await retrieve_context("数学极限怎么学", enabled=False) == []
    assert await retrieve_context("数学极限怎么学", top_k=3, enabled=False) == []


@pytest.mark.parametrize(
    "question",
    ["数学怎么提高计算准确率", "政治选择题怎么提分", "专业课如何对齐考纲"],
)
async def test_builtin_corpus_covers_core_subjects(question: str) -> None:
    reset_knowledge_base()
    chunks = await retrieve_context(question, top_k=3)
    assert chunks
