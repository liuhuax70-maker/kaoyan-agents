"""提示词设计层：角色定义、上下文渲染与模板组装。"""

from app.prompts.catalog import (
    ROLES,
    WORKER_ROLE_KEYS,
    AgentRole,
    get_role,
)
from app.prompts.context import (
    render_learner,
    render_output_contract,
    render_plan,
    render_plan_draft,
    render_reminder,
    render_subjects,
)
from app.prompts.templates import (
    PROMPT_SPECS,
    PromptSpec,
    build_messages,
    describe_prompts,
    get_prompt_spec,
)

__all__ = [
    "PROMPT_SPECS",
    "ROLES",
    "WORKER_ROLE_KEYS",
    "AgentRole",
    "PromptSpec",
    "build_messages",
    "describe_prompts",
    "get_prompt_spec",
    "get_role",
    "render_learner",
    "render_output_contract",
    "render_plan",
    "render_plan_draft",
    "render_reminder",
    "render_subjects",
]
