"""模型调用层：任务定义、模型工厂、结构化解析与离线兜底。"""

from app.llm.factory import build_chat_model, invoke_agent_task
from app.llm.offline import build_offline_payload, supports
from app.llm.structured import (
    CallStats,
    extract_json_object,
    extract_usage,
    invoke_structured,
)
from app.llm.stub import StubChatModel
from app.llm.tasks import TASK_SCHEMAS, AgentTask, schema_for

__all__ = [
    "TASK_SCHEMAS",
    "AgentTask",
    "CallStats",
    "StubChatModel",
    "build_chat_model",
    "build_offline_payload",
    "extract_json_object",
    "extract_usage",
    "invoke_agent_task",
    "invoke_structured",
    "schema_for",
    "supports",
]
