"""文本处理：分词与切片。"""

import hashlib
import re

CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
WORD_PATTERN = re.compile(r"[a-zA-Z0-9]+")
SENTENCE_ENDINGS = "。！？；\n"


def tokenize(text: str) -> list[str]:
    """中英文混合分词。

    中文按单字 + 相邻二元组切分：单字保证召回，二元组保留部分词序信息，
    让离线哈希向量也能体现「词序相近则相似」的直觉。
    """

    lowered = text.lower()
    tokens: list[str] = WORD_PATTERN.findall(lowered)

    cjk = CJK_PATTERN.findall(lowered)
    tokens.extend(cjk)
    tokens.extend(f"{cjk[index]}{cjk[index + 1]}" for index in range(len(cjk) - 1))
    return tokens


def token_hash(token: str) -> int:
    """返回稳定的 64 位哈希，跨进程一致。"""

    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def chunk_text(text: str, size: int = 320, overlap: int = 64) -> list[str]:
    """按字符滑窗切片，尽量在句子边界断开。

    Args:
        text: 原始文本。
        size: 单个片段的目标长度。
        overlap: 相邻片段的重叠长度，避免切断上下文。
    """

    cleaned = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n")).strip()
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]

    step = max(1, size - overlap)
    chunks: list[str] = []
    start = 0

    while start < len(cleaned):
        end = min(start + size, len(cleaned))
        if end < len(cleaned):
            boundary = _find_boundary(cleaned, start, end)
            if boundary > start:
                end = boundary
        fragment = cleaned[start:end].strip()
        if fragment:
            chunks.append(fragment)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + step)

    return chunks


def _find_boundary(text: str, start: int, end: int) -> int:
    """在窗口内回溯寻找最近的句子结束位置。"""

    window_start = max(start + 1, end - 80)
    for position in range(end - 1, window_start - 1, -1):
        if text[position] in SENTENCE_ENDINGS:
            return position + 1
    return end


def normalize_vector(vector: list[float]) -> list[float]:
    """L2 归一化，便于直接使用余弦相似度。"""

    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算余弦相似度，长度不一致时返回 0。"""

    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(a * b for a, b in zip(left, right, strict=True)))
