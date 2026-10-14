"""模型调用层：任务定义、模型工厂与结构化解析。"""

from app.llm.factory import build_chat_model, invoke_agent_task, invoke_subagent_task
from app.llm.structured import (
    CallStats,
    extract_json_object,
    extract_usage,
    invoke_structured,
    message_text,
)
from app.llm.tasks import (
    SUBAGENT_TASKS,
    TASK_SCHEMAS,
    AgentTask,
    output_model_for,
    schema_for,
)

__all__ = [
    "SUBAGENT_TASKS",
    "TASK_SCHEMAS",
    "AgentTask",
    "CallStats",
    "build_chat_model",
    "extract_json_object",
    "extract_usage",
    "invoke_agent_task",
    "invoke_structured",
    "invoke_subagent_task",
    "message_text",
    "output_model_for",
    "schema_for",
]