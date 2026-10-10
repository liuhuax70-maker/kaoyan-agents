"""计划评审多角色协作（CrewAI）。

分工原则：LangGraph 负责状态机编排与动态扇出，CrewAI 负责角色化协作。
这里让「评审专家」先挑问题，「规划师」再据此给出修订结论，
形成一轮真正有对抗性的计划评审，而不是自说自话。
"""

from typing import Any

from crewai import Agent, Crew, Process, Task

from app.core.config import get_settings
from app.core.logging import get_logger
from app.crews.llm import KaoyanCrewLLM
from app.llm import AgentTask, build_chat_model, extract_json_object, invoke_structured
from app.prompts import (
    build_messages,
    render_learner,
    render_output_contract,
    render_plan_draft,
)
from app.prompts.catalog import PLANNER_ROLE, REVIEWER_ROLE
from app.schemas import LearnerSnapshot, PlanDraft, PlanReviewResult

logger = get_logger(__name__)

CREW_REVIEWER = "plan-review-crew"
LOCAL_REVIEWER = "local-single-agent"

REVIEW_TASK_DESCRIPTION = """对下面这份备考计划做一次严格评审。

【考生画像】
{learner_context}

【计划草稿】
{plan_context}

逐项检查并指出问题：
1. 任务粒度：是否存在超过单次专注时长的任务；
2. 阶段划分：是否覆盖整个备考周期并设有阶段性检验点；
3. 科目覆盖：薄弱科目是否被安排且优先级更高；
4. 时间可行性：每日任务总量是否超出考生的可投入时长；
5. 输入完整性：档案是否缺少考试日期等关键信息。

每条问题都要引用计划中的具体数据，不要给泛泛而谈的评价。
"""

FINALIZE_TASK_DESCRIPTION = """基于上一步的评审意见，给出最终评审结论。

【输出结构】
{output_contract}

要求：
- approved 仅在没有任何 high 级问题时为 true；
- score 为 0 到 100 的整数，问题越严重扣分越多；
- issues 中每条都必须包含 severity、category、detail、suggestion；
- improvements 给出 3 条具体的计划修订要点；
- reviewer 字段固定填写 "{reviewer}"。
"""


def plan_review_context(learner: LearnerSnapshot, draft: PlanDraft) -> dict[str, Any]:
    """构造评审上下文，真实模型与离线桩共用同一份数据。"""

    durations = [
        task.duration_minutes for stage in draft.stages for task in stage.tasks
    ] or [0]
    return {
        "subjects": learner.subject_names,
        "weak_subjects": learner.weak_subjects,
        "days_left": learner.days_left,
        "daily_hours": learner.daily_hours,
        "attention_span": learner.attention_span,
        "horizon_days": draft.horizon_days,
        "stage_count": len(draft.stages),
        "task_count": draft.total_tasks,
        "max_task_minutes": max(durations),
    }


def build_review_crew(
    learner: LearnerSnapshot,
    draft: PlanDraft,
    provider: str | None = None,
) -> Crew:
    """构建「评审专家 → 规划师」顺序协作的 Crew。"""

    context = plan_review_context(learner, draft)
    reviewer_llm = KaoyanCrewLLM(
        model=AgentTask.PLAN_REVIEW.value, provider_name=provider, stub_context=context
    )
    planner_llm = KaoyanCrewLLM(
        model=AgentTask.PLAN_REVIEW.value, provider_name=provider, stub_context=context
    )

    reviewer = Agent(
        role=REVIEWER_ROLE.name,
        goal=REVIEWER_ROLE.mission,
        backstory=REVIEWER_ROLE.system_prompt,
        llm=reviewer_llm,
        allow_delegation=False,
        verbose=False,
    )
    planner = Agent(
        role=PLANNER_ROLE.name,
        goal=PLANNER_ROLE.mission,
        backstory=PLANNER_ROLE.system_prompt,
        llm=planner_llm,
        allow_delegation=False,
        verbose=False,
    )

    review_task = Task(
        description=REVIEW_TASK_DESCRIPTION.format(
            learner_context=render_learner(learner),
            plan_context=render_plan_draft(draft),
        ),
        expected_output="逐条列出的计划问题清单，每条包含严重程度、数据依据与修改建议",
        agent=reviewer,
    )
    finalize_task = Task(
        description=FINALIZE_TASK_DESCRIPTION.format(
            output_contract=render_output_contract(PlanReviewResult),
            reviewer=CREW_REVIEWER,
        ),
        expected_output="满足给定 JSON 结构的评审结论对象",
        agent=planner,
        context=[review_task],
    )

    return Crew(
        agents=[reviewer, planner],
        tasks=[review_task, finalize_task],
        process=Process.sequential,
        verbose=False,
    )


async def review_plan_with_crew(
    learner: LearnerSnapshot,
    draft: PlanDraft,
    provider: str | None = None,
) -> PlanReviewResult:
    """执行一次两角色 CrewAI 评审协作。"""

    crew = build_review_crew(learner, draft, provider)
    output = await crew.kickoff_async()
    result = PlanReviewResult.model_validate(extract_json_object(str(output)))
    result.reviewer = CREW_REVIEWER
    return result


async def review_plan_locally(
    learner: LearnerSnapshot,
    draft: PlanDraft,
) -> PlanReviewResult:
    """单智能体离线评审，不依赖 CrewAI 运行时。"""

    context = plan_review_context(learner, draft)
    messages = build_messages(
        AgentTask.PLAN_REVIEW,
        learner_context=render_learner(learner),
        plan_context=render_plan_draft(draft),
    )
    model = build_chat_model(AgentTask.PLAN_REVIEW.value, "stub", stub_context=context)
    result = await invoke_structured(model, messages, PlanReviewResult)
    result.reviewer = LOCAL_REVIEWER
    return result


async def review_plan(
    learner: LearnerSnapshot,
    draft: PlanDraft,
    provider: str | None = None,
    process: str | None = None,
) -> PlanReviewResult:
    """评审学习计划。

    优先走 CrewAI 多角色协作；协作失败时回退单智能体评审，
    保证「评审」这一环节不会因为框架或网络问题而整体失败。
    """

    settings = get_settings()
    mode = process or settings.workflow.plan_review_process

    if mode == "crew":
        try:
            return await review_plan_with_crew(learner, draft, provider)
        except Exception as exc:  # noqa: BLE001 - 协作失败必须能降级
            logger.warning("CrewAI 计划评审失败，回退单智能体评审：%s", exc)

    return await review_plan_locally(learner, draft)
