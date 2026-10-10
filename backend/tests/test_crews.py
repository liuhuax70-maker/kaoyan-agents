"""CrewAI 多角色协作测试：装配、消息适配、评审逻辑与工作流集成。"""

from crewai import Crew
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.crews import (
    build_review_crew,
    plan_review_context,
    review_plan,
    review_plan_locally,
)
from app.crews.llm import KaoyanCrewLLM, as_text, to_langchain_messages
from app.llm import AgentTask
from app.schemas import LearnerSnapshot, PlanDraft, PlanReviewResult, SubjectSnapshot
from app.workflows import run_workflow


def _learner(attention_span: int = 60) -> LearnerSnapshot:
    return LearnerSnapshot(
        nickname="小研",
        target_title="复旦计算机",
        days_left=120,
        daily_hours=5,
        attention_span=attention_span,
        self_discipline=4,
        subjects=[
            SubjectSnapshot(name="数学", score_weight=0.3, is_weak=True),
            SubjectSnapshot(name="英语", score_weight=0.2),
        ],
    )


def _draft(task_minutes: int = 45, stages: int = 3) -> PlanDraft:
    tasks = [
        {"title": "数学第一章精读", "subject": "数学", "duration_minutes": task_minutes},
        {"title": "英语真题阅读两篇", "subject": "英语", "duration_minutes": 40},
    ]
    stage_payloads = [
        {
            "name": name,
            "stage_type": stage_type,
            "start_offset": index * 40,
            "end_offset": (index + 1) * 40,
            "focus": f"{name}阶段重点",
            "tasks": tasks,
        }
        for index, (name, stage_type) in enumerate(
            [
                ("基础夯实", "foundation"),
                ("强化提升", "enhancement"),
                ("真题冲刺", "sprint"),
            ][:stages]
        )
    ]
    return PlanDraft.model_validate(
        {
            "title": "120 天备考计划",
            "goal": "系统完成数学与英语备考并进入模考状态",
            "strategy": "分阶段推进，薄弱科目优先",
            "horizon_days": 120,
            "daily_hours": 5,
            "stages": stage_payloads,
        }
    )


def test_message_conversion_handles_string_and_blocks() -> None:
    single = to_langchain_messages("你好")
    assert len(single) == 1
    assert isinstance(single[0], HumanMessage)

    converted = to_langchain_messages(
        [
            {"role": "system", "content": "系统提示"},
            {"role": "assistant", "content": [{"text": "上一步结论"}]},
            {"role": "user", "content": "继续"},
        ]
    )
    assert isinstance(converted[0], SystemMessage)
    assert isinstance(converted[1], AIMessage)
    assert converted[1].content == "上一步结论"
    assert isinstance(converted[2], HumanMessage)


def test_as_text_flattens_content_blocks() -> None:
    assert as_text("文本") == "文本"
    assert as_text([{"text": "a"}, "b", {"type": "image"}]) == "ab"
    assert as_text(None) == ""


def test_crew_is_assembled_with_two_roles_in_order() -> None:
    """Crew 应包含评审专家与规划师两个角色，且评审任务在修订任务之前。"""

    crew = build_review_crew(_learner(), _draft())
    assert isinstance(crew, Crew)
    assert len(crew.agents) == 2
    assert len(crew.tasks) == 2
    assert crew.agents[0].role == "复盘诊断师"
    assert crew.agents[1].role == "备考规划师"
    assert crew.tasks[0].agent.role == "复盘诊断师"
    assert crew.tasks[1].agent.role == "备考规划师"
    assert crew.tasks[1].context == [crew.tasks[0]]
    assert isinstance(crew.agents[0].llm, KaoyanCrewLLM)


def test_review_context_extracts_plan_metrics() -> None:
    context = plan_review_context(_learner(), _draft(task_minutes=90))
    assert context["max_task_minutes"] == 90
    assert context["stage_count"] == 3
    assert context["task_count"] == 6
    assert context["horizon_days"] == 120
    assert context["weak_subjects"] == ["数学"]


async def test_local_review_flags_oversized_task() -> None:
    """任务时长超过单次专注时长时，应给出 high 级问题并否决计划。"""

    result = await review_plan_locally(_learner(attention_span=60), _draft(task_minutes=120))

    assert isinstance(result, PlanReviewResult)
    assert result.approved is False
    categories = [item.category for item in result.issues]
    assert "任务粒度" in categories
    assert result.blocking_issues
    assert result.score < 100


async def test_local_review_approves_reasonable_plan() -> None:
    result = await review_plan_locally(_learner(attention_span=90), _draft(task_minutes=45))
    assert result.approved is True
    assert result.improvements


async def test_review_plan_runs_crew_offline() -> None:
    """无大模型密钥时，CrewAI 协作仍应能真实执行并产出结构化结论。"""

    result = await review_plan(
        _learner(attention_span=60), _draft(task_minutes=120), process="crew"
    )

    assert isinstance(result, PlanReviewResult)
    assert result.summary
    assert result.issues


async def test_review_plan_falls_back_to_local_on_failure() -> None:
    """未知执行方式时应回退到单智能体评审，而不是直接失败。"""

    result = await review_plan(_learner(), _draft(), process="unknown-mode")
    assert result.reviewer == "local-single-agent"


async def test_workflow_attaches_plan_review_when_enabled() -> None:
    result = await run_workflow("帮我制定复习计划", _learner(), enable_review=True)

    assert result.plan_draft is not None
    assert result.plan_review is not None
    assert isinstance(result.plan_review, PlanReviewResult)


async def test_workflow_skips_review_when_disabled() -> None:
    result = await run_workflow("帮我制定复习计划", _learner(), enable_review=False)
    assert result.plan_draft is not None
    assert result.plan_review is None


def test_crew_llm_declares_expected_interface() -> None:
    llm = KaoyanCrewLLM(model=AgentTask.PLAN_REVIEW.value, stub_context={})
    assert llm.llm_type == "kaoyan-crew"
    assert llm.model == "plan_review"
    assert llm.supports_stop_words() is False
    assert llm.stop_sequences == []
    assert llm.get_context_window_size() == 8192
