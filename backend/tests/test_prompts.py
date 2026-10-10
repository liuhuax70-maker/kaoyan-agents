"""提示词体系测试：角色定义、模板组装与输出契约注入。"""

import pytest

from app.core.errors import PromptError
from app.llm.tasks import AgentTask
from app.prompts import (
    ROLES,
    WORKER_ROLE_KEYS,
    build_messages,
    describe_prompts,
    render_learner,
    render_plan,
    render_subjects,
)
from app.schemas import LearnerSnapshot, PlanSnapshot, SubjectSnapshot, TaskSnapshot


def _snapshot() -> LearnerSnapshot:
    return LearnerSnapshot(
        nickname="小研",
        target_title="复旦计算机",
        exam_type="postgraduate",
        days_left=200,
        daily_hours=6,
        weekly_days=6,
        attention_span=60,
        self_discipline=4,
        preferred_slots=["上午"],
        subjects=[
            SubjectSnapshot(name="数学", score_weight=0.3, is_weak=True, difficulty=5),
            SubjectSnapshot(name="英语", score_weight=0.2),
        ],
    )


def test_roles_are_fully_defined() -> None:
    """每个角色的提示词都必须包含输出契约与领域约束。"""

    assert set(WORKER_ROLE_KEYS) <= set(ROLES)
    assert "coordinator" in ROLES

    for role in ROLES.values():
        assert role.name
        assert role.mission
        assert "输出契约" in role.system_prompt
        assert "领域约束" in role.system_prompt
        assert "简体中文" in role.system_prompt


def test_prompt_catalog_covers_all_tasks() -> None:
    """每个任务都必须配置提示词模板。"""

    described = describe_prompts()
    assert {item["task"] for item in described} == {task.value for task in AgentTask}
    assert all(item["system_prompt"] for item in described)


def test_build_messages_injects_output_contract() -> None:
    """输出契约应自动注入到用户消息中，保证提示词与 Schema 同步。"""

    messages = build_messages(
        AgentTask.PLAN_DRAFT,
        learner_context=render_learner(_snapshot()),
        subject_context=render_subjects(_snapshot()),
        request="帮我制定从现在到考试的复习计划",
    )

    assert len(messages) == 2
    assert messages[0].type == "system"
    assert messages[1].type == "human"

    human = str(messages[1].content)
    assert "帮我制定从现在到考试的复习计划" in human
    assert "horizon_days" in human
    assert "day_offset" in human
    assert "输出结构" in human


def test_build_messages_raises_on_missing_variable() -> None:
    """缺少必需变量时应给出明确错误，而不是把占位符发给模型。"""

    with pytest.raises(PromptError) as excinfo:
        build_messages(AgentTask.PLAN_DRAFT, learner_context="昵称：小研")

    assert "subject_context" in str(excinfo.value)


def test_render_learner_contains_key_facts() -> None:
    text = render_learner(_snapshot())
    assert "剩余天数：200 天" in text
    assert "每日可投入：6 小时" in text
    assert "每周约 36 小时" in text
    assert "自律程度：4/5" in text


def test_render_subjects_marks_weak_subjects() -> None:
    text = render_subjects(_snapshot())
    assert "数学【薄弱】" in text
    assert "分值占比 30%" in text


def test_render_plan_lists_tasks() -> None:
    plan = PlanSnapshot(
        title="200 天备考规划",
        horizon_days=200,
        status="active",
        tasks=[
            TaskSnapshot(
                title="高数第一章精读",
                subject="数学",
                status="done",
                duration_minutes=90,
                priority="high",
            )
        ],
    )
    text = render_plan(plan)
    assert "任务总数：1" in text
    assert "[done]" in text
    assert "高数第一章精读" in text

    assert render_plan(None) == "（当前没有进行中的学习计划）"
