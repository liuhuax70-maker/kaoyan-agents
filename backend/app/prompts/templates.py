"""各智能体的对话提示词模板。

模板与角色、结构化输出 Schema 一一绑定：调用方只需给出任务与变量，
输出契约由模板自动注入，避免提示词与 Schema 不同步。
"""

from dataclasses import dataclass

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

from app.core.errors import PromptError
from app.llm.tasks import AgentTask, output_model_for
from app.prompts.catalog import (
    BREAKDOWN_ROLE,
    COACH_ROLE,
    PLAN_EDITOR_ROLE,
    PLANNER_ROLE,
    RESOURCE_ROLE,
    REVIEWER_ROLE,
    SCHOOL_ADVISOR_ROLE,
    AgentRole,
)
from app.prompts.catalog import TUTOR_ROLE as TUTOR_ROLE_DEF
from app.prompts.context import render_output_contract

PLAN_USER_TEMPLATE = """【考生画像】
{learner_context}

【科目清单】
{subject_context}

【本次诉求】
{request}

【输出结构】
{output_contract}
"""

BREAKDOWN_USER_TEMPLATE = """【考生画像】
{learner_context}

【科目清单】
{subject_context}

【待拆解的阶段或目标】
{scope}

【输出结构】
{output_contract}
"""

TUTOR_USER_TEMPLATE = """【考生画像】
{learner_context}

【考生提出的问题】
{request}

【知识库参考资料】
{retrieved_context}

【输出结构】
{output_contract}
"""

DIAGNOSIS_USER_TEMPLATE = """【考生画像】
{learner_context}

【当前计划】
{plan_context}

【复盘诉求】
{request}

【输出结构】
{output_contract}
"""

RESOURCE_USER_TEMPLATE = """【考生画像】
{learner_context}

【科目清单】
{subject_context}

【资料需求】
{request}

【知识库参考资料】
{retrieved_context}

【输出结构】
{output_contract}
"""

NUDGE_USER_TEMPLATE = """【考生画像】
{learner_context}

【提醒要素】
{reminder_context}

【输出结构】
{output_contract}
"""

DIGEST_USER_TEMPLATE = """【考生画像】
{learner_context}

【本周数据】
{plan_context}

【输出结构】
{output_contract}
"""

REVIEW_USER_TEMPLATE = """【考生画像】
{learner_context}

【待评审的计划草稿】
{plan_context}

【输出结构】
{output_contract}
"""

REVISION_USER_TEMPLATE = """【考生画像】
{learner_context}

【当前计划表】
{plan_context}

【用户诉求】
{request}

【执行说明】
只修订用户明确要求的部分，不要顺手重排整份计划。

【输出结构】
{output_contract}
"""

SCHOOL_ADVISOR_USER_TEMPLATE = """【考生画像】
{learner_context}

【考生诉求】
{request}

【联网检索到的线索】
{retrieved_context}

【官方核验入口】
{official_links}

【执行说明】
线索可能过期或有误，只能作为参考方向；不得把里面的分数、比例当作事实复述。
核验入口由系统给出，引用即可，不要自行编造院校网址。

【输出结构】
{output_contract}
"""

SCHOOL_BRIEF_USER_TEMPLATE = """【考生画像】
{learner_context}

【正在跟踪的院校】
{tracked_context}

【联网检索到的线索】
{retrieved_context}

【输出结构】
{output_contract}
"""

@dataclass(frozen=True, slots=True)
class PromptSpec:
    """任务与提示词的绑定关系。"""

    task: AgentTask
    role: AgentRole
    template: ChatPromptTemplate
    required_variables: tuple[str, ...] = ()
    optional_variables: tuple[str, ...] = ()


def _make(role: AgentRole, user_template: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [("system", role.system_prompt), ("human", user_template)]
    )


PROMPT_SPECS: dict[AgentTask, PromptSpec] = {
    AgentTask.PLAN_DRAFT: PromptSpec(
        task=AgentTask.PLAN_DRAFT,
        role=PLANNER_ROLE,
        template=_make(PLANNER_ROLE, PLAN_USER_TEMPLATE),
        required_variables=("learner_context", "subject_context", "request"),
    ),
    AgentTask.TASK_BREAKDOWN: PromptSpec(
        task=AgentTask.TASK_BREAKDOWN,
        role=BREAKDOWN_ROLE,
        template=_make(BREAKDOWN_ROLE, BREAKDOWN_USER_TEMPLATE),
        required_variables=("learner_context", "subject_context", "scope"),
    ),
    AgentTask.TUTORING: PromptSpec(
        task=AgentTask.TUTORING,
        role=TUTOR_ROLE_DEF,
        template=_make(TUTOR_ROLE_DEF, TUTOR_USER_TEMPLATE),
        required_variables=("learner_context", "request", "retrieved_context"),
    ),
    AgentTask.DIAGNOSIS: PromptSpec(
        task=AgentTask.DIAGNOSIS,
        role=REVIEWER_ROLE,
        template=_make(REVIEWER_ROLE, DIAGNOSIS_USER_TEMPLATE),
        required_variables=("learner_context", "plan_context", "request"),
    ),
    AgentTask.RESOURCE_PLAN: PromptSpec(
        task=AgentTask.RESOURCE_PLAN,
        role=RESOURCE_ROLE,
        template=_make(RESOURCE_ROLE, RESOURCE_USER_TEMPLATE),
        required_variables=("learner_context", "subject_context", "request", "retrieved_context"),
    ),
    AgentTask.NUDGE: PromptSpec(
        task=AgentTask.NUDGE,
        role=COACH_ROLE,
        template=_make(COACH_ROLE, NUDGE_USER_TEMPLATE),
        required_variables=("learner_context", "reminder_context"),
    ),
    AgentTask.WEEKLY_DIGEST: PromptSpec(
        task=AgentTask.WEEKLY_DIGEST,
        role=COACH_ROLE,
        template=_make(COACH_ROLE, DIGEST_USER_TEMPLATE),
        required_variables=("learner_context", "plan_context"),
    ),
    AgentTask.PLAN_REVIEW: PromptSpec(
        task=AgentTask.PLAN_REVIEW,
        role=REVIEWER_ROLE,
        template=_make(REVIEWER_ROLE, REVIEW_USER_TEMPLATE),
        required_variables=("learner_context", "plan_context"),
    ),
    AgentTask.PLAN_REVISION: PromptSpec(
        task=AgentTask.PLAN_REVISION,
        role=PLAN_EDITOR_ROLE,
        template=_make(PLAN_EDITOR_ROLE, REVISION_USER_TEMPLATE),
        required_variables=("learner_context", "plan_context", "request"),
    ),
    AgentTask.SCHOOL_ADVISOR: PromptSpec(
        task=AgentTask.SCHOOL_ADVISOR,
        role=SCHOOL_ADVISOR_ROLE,
        template=_make(SCHOOL_ADVISOR_ROLE, SCHOOL_ADVISOR_USER_TEMPLATE),
        required_variables=("learner_context", "request", "retrieved_context", "official_links"),
    ),
    AgentTask.SCHOOL_BRIEF: PromptSpec(
        task=AgentTask.SCHOOL_BRIEF,
        role=SCHOOL_ADVISOR_ROLE,
        template=_make(SCHOOL_ADVISOR_ROLE, SCHOOL_BRIEF_USER_TEMPLATE),
        required_variables=("learner_context", "tracked_context", "retrieved_context"),
    ),
}


def get_prompt_spec(task: AgentTask) -> PromptSpec:
    """获取任务对应的提示词规格。"""

    try:
        return PROMPT_SPECS[task]
    except KeyError as exc:  # pragma: no cover - 仅在登记遗漏时触发
        raise PromptError(f"任务 {task} 未配置提示词模板") from exc


def build_messages(task: AgentTask, **variables: str) -> list[BaseMessage]:
    """组装最终发送给模型的消息列表。"""

    spec = get_prompt_spec(task)
    missing = [name for name in spec.required_variables if not variables.get(name)]
    if missing:
        raise PromptError(f"任务 {task} 缺少必需变量：{'、'.join(missing)}")

    # 契约取的是「实际会被解析的输出模型」：子智能体任务是套了双轨信封的那个，
    # 因此模型被要求输出的结构，与随后用来解析的结构，永远是同一个
    payload = {**variables, "output_contract": render_output_contract(output_model_for(task))}
    return spec.template.format_messages(**payload)


def describe_prompts() -> list[dict[str, object]]:
    """返回提示词清单，供文档与调试接口使用。"""

    return [
        {
            "task": spec.task.value,
            "role": spec.role.key,
            "role_name": spec.role.name,
            "required_variables": list(spec.required_variables),
            "system_prompt": spec.role.system_prompt,
        }
        for spec in PROMPT_SPECS.values()
    ]
