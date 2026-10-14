"""择校参谋：结构约束、工具路由与候选院校落库。

分层验证：Schema 断言「不替用户做决定」的四层结构防线，
工作流断言工具路由与核验入口注入，服务层断言候选只在用户动作下才升级。
"""

from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.db.models import (
    AgentConversation,
    ExamTarget,
    ExamType,
    TargetStatus,
    TrackedSchool,
    TrackedSchoolStatus,
    User,
)
from app.llm import output_model_for
from app.llm.tasks import AgentTask
from app.prompts import ROLES
from app.prompts.context import render_output_contract
from app.schemas import SchoolAdvisorAnswer
from app.services.conversations import CommitContext, persist_result
from app.services.targets import (
    archive_school,
    decide_school,
    list_tracked_schools,
    upsert_candidates,
)
from app.workflows import run_workflow
from app.workflows.runner import build_result
from tests.fakes import FAKE_SCHOOL_CANDIDATES, build_school_advice
from tests.test_workflow import _learner


@pytest.fixture
def search_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """打开联网搜索并注入密钥，让择校走「有线索」的那条路径。

    只替换 ``get_settings``，不替换 ``build_search_client``：提供方选择与
    「缺密钥应报配置错误」这些真实逻辑全部保留，被替换的只有最外层的网络调用
    （见 conftest 的 ``install_fake_search``）。
    """

    from types import SimpleNamespace

    from app.core.config import SearchSection
    from app.search import base as base_module
    from app.search import client as client_module

    section = SearchSection(enabled=True, tavily_api_key="test-key")
    stub = SimpleNamespace(search=section)
    monkeypatch.setattr(base_module, "get_settings", lambda: stub)
    monkeypatch.setattr(client_module, "get_settings", lambda: stub)


def _candidate(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "某某大学",
        "major": "计算机技术",
        "fit_for": "基础扎实且愿意接受高强度竞争的考生",
        "pros": ["专业课资料容易找到"],
        "cons": ["复试竞争激烈"],
    }
    payload.update(overrides)
    return payload


def _answer(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidates": [
            _candidate(name="某某大学", fit_for="基础扎实且愿意接受高强度竞争的考生"),
            _candidate(name="某某理工大学", fit_for="希望稳妥落地、看重一次上岸的考生"),
            _candidate(name="某某师范大学", fit_for="愿意转向教育方向、跨考压力较小的考生"),
        ]
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Schema：用结构而不是提示词来强制「不替用户做决定」
# --------------------------------------------------------------------------


def test_candidate_rejects_ranking_fields() -> None:
    """排序、推荐、结论这类字段根本不存在，模型吐出来就是校验错误。"""

    for extra in ({"rank": 1}, {"recommended": True}, {"score": 95}, {"best_choice": "某某大学"}):
        with pytest.raises(ValidationError):
            SchoolAdvisorAnswer.model_validate(
                _answer(candidates=[{**_candidate(), **extra}, *_answer()["candidates"][1:]])
            )


def test_answer_requires_at_least_three_candidates() -> None:
    """只给一两所等于替用户缩窄了选择，必须在解析期拦下。"""

    with pytest.raises(ValidationError):
        SchoolAdvisorAnswer.model_validate(_answer(candidates=_answer()["candidates"][:2]))


def test_candidate_requires_both_pros_and_cons() -> None:
    """没有劣势的院校不存在，空列表是退化输出。"""

    with pytest.raises(ValidationError):
        SchoolAdvisorAnswer.model_validate(
            _answer(candidates=[{**_candidate(), "cons": []}, *_answer()["candidates"][1:]])
        )


def test_answer_rejects_duplicate_names() -> None:
    candidates = _answer()["candidates"]
    duplicate = {**candidates[1], "name": candidates[0]["name"]}
    with pytest.raises(ValidationError, match="不得重复"):
        SchoolAdvisorAnswer.model_validate(
            _answer(candidates=[candidates[0], duplicate, candidates[2]])
        )


def test_answer_rejects_duplicate_fit_for() -> None:
    """换所学校但适用人群一字不改，等于只给了一个答案。"""

    candidates = _answer()["candidates"]
    duplicate = {**candidates[1], "fit_for": candidates[0]["fit_for"]}
    with pytest.raises(ValidationError, match="适用人群描述不得雷同"):
        SchoolAdvisorAnswer.model_validate(
            _answer(candidates=[candidates[0], duplicate, candidates[2]])
        )


def test_output_contract_declares_additional_properties_false() -> None:
    """守住第一层防线赖以成立的机制。

    只有 ``extra="forbid"`` 才会在 JSON Schema 里写出 ``additionalProperties: false``，
    而提示词渲染只剥掉字符串型的 ``title`` 注解。将来若改动渲染逻辑，
    这条断言会先红——否则「禁止排序字段」会静默退化成一句无人执行的散文。
    """

    contract = render_output_contract(output_model_for(AgentTask.SCHOOL_ADVISOR))
    assert '"additionalProperties": false' in contract.replace("\n", " ")
    assert "rank" not in contract
    assert "recommended" not in contract


def test_role_restates_invariants_not_visible_in_schema() -> None:
    """跨字段校验不会出现在 JSON Schema 里，因此必须在专属规则里复述一遍。"""

    rules = "".join(ROLES["school_advisor"].extra_rules)
    assert "不得彼此雷同" in rules
    assert "不得输出「首选」" in rules or "严禁任何形式的排序" in rules
    assert "决定权落在用户身上" in rules


# --------------------------------------------------------------------------
# 工作流：工具路由与确定性核验入口
# --------------------------------------------------------------------------


async def test_advise_schools_presents_multiple_candidates() -> None:
    """择校诉求应路由到参谋，并给出多所候选与逐项利弊，且不含任何排序字段。"""

    result = await run_workflow("帮我看看计算机考研该选哪些院校，报录比怎么样", _learner())

    assert [item.name for item in result.tool_calls] == ["advise_schools"]

    advice = result.school_advice
    assert advice is not None
    assert len(advice.candidates) >= 3
    for candidate in advice.candidates:
        assert candidate.pros and candidate.cons

    # 结构化产出里不得出现排序、推荐这类字段（连键都不该有）
    dumped = result.outputs[0].payload
    assert "rank" not in dumped
    assert "recommended" not in dumped

    reply = result.reply_text()
    assert reply.strip()
    assert "择校候选" in reply


async def test_advise_schools_injects_official_links_and_never_fabricates_hosts() -> None:
    """核验入口由系统注入，模型的自述一律被覆盖；主机名只能是白名单站点。"""

    from httpx import URL

    result = await run_workflow("计算机考研择校怎么选", _learner())

    advice = result.school_advice
    assert advice is not None
    assert advice.verification_links
    for mark in advice.verification_links:
        url = mark.split("](")[-1].rstrip(")")
        assert URL(url).host in {"yz.chsi.com.cn", "www.baidu.com"}

    highlights = " ".join(result.outputs[0].highlights)
    assert "核验入口" in highlights


async def test_advise_schools_keeps_web_hits_as_citations(
    search_enabled: None,
) -> None:
    """联网片段要进引用列表，且来源显示页面标题、URL 放在 metadata 里。"""

    result = await run_workflow("计算机考研择校怎么选", _learner(), enable_search=True)

    references = result.outputs[0].payload.get("references") or []
    assert references
    web = [item for item in references if item["metadata"].get("url")]
    assert web
    assert web[0]["source"] == web[0]["metadata"]["title"]


# --------------------------------------------------------------------------
# 服务层：候选落库与「只有用户能拍板」
# --------------------------------------------------------------------------


async def _seed(app_db) -> tuple[User, ExamTarget]:
    user = User(username="kaoyan", nickname="小研")
    app_db.add(user)
    await app_db.flush()

    target = ExamTarget(
        user_id=user.id,
        exam_type=ExamType.POSTGRADUATE,
        title="计算机考研",
        exam_date=date(2027, 12, 20),
        status=TargetStatus.PREPARING,
    )
    app_db.add(target)
    await app_db.flush()
    return user, target


async def test_upsert_candidates_is_idempotent(app_db) -> None:
    """同一批候选重复落库只更新快照，不产生重复行。"""

    user, target = await _seed(app_db)
    answer = SchoolAdvisorAnswer.model_validate(build_school_advice({}))

    first = await upsert_candidates(
        app_db, user_id=user.id, target_id=target.id, answer=answer
    )
    second = await upsert_candidates(
        app_db, user_id=user.id, target_id=target.id, answer=answer
    )

    assert len(first) == len(FAKE_SCHOOL_CANDIDATES)
    assert {item.id for item in first} == {item.id for item in second}

    rows = await list_tracked_schools(app_db, target_id=target.id)
    assert len(rows) == len(FAKE_SCHOOL_CANDIDATES)
    assert all(item.status is TrackedSchoolStatus.CANDIDATE for item in rows)


async def test_upsert_keeps_decided_status(app_db) -> None:
    """已经拍板的院校不会被下一次咨询悄悄降回候选。"""

    user, target = await _seed(app_db)
    answer = SchoolAdvisorAnswer.model_validate(build_school_advice({}))
    await upsert_candidates(app_db, user_id=user.id, target_id=target.id, answer=answer)

    rows = await list_tracked_schools(app_db, target_id=target.id)
    chosen = await decide_school(app_db, target_id=target.id, school_id=rows[0].id)
    assert chosen is not None

    await upsert_candidates(app_db, user_id=user.id, target_id=target.id, answer=answer)
    refreshed = await app_db.get(TrackedSchool, rows[0].id)
    assert refreshed is not None
    assert refreshed.status is TrackedSchoolStatus.DECIDED


async def test_candidates_stay_candidate_when_persisted(app_db) -> None:
    """参谋落库绝不改动备考目标 —— 写回只在用户的显式动作里发生。"""

    user, target = await _seed(app_db)
    result = await run_workflow("计算机考研择校怎么选", _learner())
    assert result.school_advice is not None

    conversation = AgentConversation(
        user_id=user.id, target_id=target.id, title="择校", workflow="multi_agent_chat"
    )
    app_db.add(conversation)
    await app_db.flush()

    commit = CommitContext(
        user_id=user.id,
        conversation_id=conversation.id,
        target_id=target.id,
        plan=None,
        thread_id="t1",
    )
    state = {"school_advice": result.school_advice.model_dump(mode="json")}
    await persist_result(app_db, commit, build_result(state))

    rows = await list_tracked_schools(app_db, target_id=target.id)
    assert rows
    assert all(item.status is TrackedSchoolStatus.CANDIDATE for item in rows)

    await app_db.refresh(target)
    assert target.target_school == ""


async def test_decide_school_writes_back_to_target(app_db) -> None:
    """用户拍板是唯一会写回目标院校的路径，且每用户至多一个 DECIDED。"""

    user, target = await _seed(app_db)
    answer = SchoolAdvisorAnswer.model_validate(build_school_advice({}))
    rows = await upsert_candidates(
        app_db, user_id=user.id, target_id=target.id, answer=answer
    )

    await decide_school(app_db, target_id=target.id, school_id=rows[0].id)
    await app_db.refresh(target)
    assert target.target_school == rows[0].name

    # 换校：旧的那所降回候选，而不是删掉
    await decide_school(app_db, target_id=target.id, school_id=rows[1].id)
    await app_db.refresh(target)
    assert target.target_school == rows[1].name

    decided = list(
        await app_db.scalars(
            select(TrackedSchool).where(TrackedSchool.status == TrackedSchoolStatus.DECIDED)
        )
    )
    assert len(decided) == 1
    assert decided[0].id == rows[1].id


async def test_decide_rejects_school_from_another_target(app_db) -> None:
    """跨目标的 school_id 不该被接受，否则会写错目标院校。"""

    user, target = await _seed(app_db)
    other = ExamTarget(
        user_id=user.id,
        exam_type=ExamType.POSTGRADUATE,
        title="另一个目标",
        exam_date=target.exam_date + timedelta(days=30),
        status=TargetStatus.PREPARING,
    )
    app_db.add(other)
    await app_db.flush()

    answer = SchoolAdvisorAnswer.model_validate(build_school_advice({}))
    rows = await upsert_candidates(
        app_db, user_id=user.id, target_id=target.id, answer=answer
    )

    assert await decide_school(app_db, target_id=other.id, school_id=rows[0].id) is None
    await app_db.refresh(other)
    assert other.target_school == ""


async def test_archive_school_keeps_row(app_db) -> None:
    """归档是状态迁移而不是删除：历史会话里提到的院校不能凭空消失。"""

    user, target = await _seed(app_db)
    answer = SchoolAdvisorAnswer.model_validate(build_school_advice({}))
    rows = await upsert_candidates(
        app_db, user_id=user.id, target_id=target.id, answer=answer
    )

    archived = await archive_school(app_db, target_id=target.id, school_id=rows[0].id)
    assert archived is not None
    assert archived.status is TrackedSchoolStatus.ARCHIVED

    assert await app_db.get(TrackedSchool, rows[0].id) is not None


# --------------------------------------------------------------------------
# 接口层：目标下的候选院校
# --------------------------------------------------------------------------


async def _seed_via_client(client) -> tuple[int, int, list[int]]:
    """用接口建用户与目标，再借服务层灌入候选，返回 (user_id, target_id, school_ids)。"""

    from app.db.session import db

    user = await client.post("/api/users", json={"username": "kaoyan", "nickname": "小研"})
    user_id = user.json()["id"]

    created = await client.post(
        "/api/targets",
        json={
            "user_id": user_id,
            "title": "计算机考研",
            "exam_date": date(2027, 12, 20).isoformat(),
            "subjects": [{"name": "数学", "is_weak": True}],
        },
    )
    target_id = created.json()["id"]

    answer = SchoolAdvisorAnswer.model_validate(build_school_advice({}))
    async with db.session_factory() as session:
        rows = await upsert_candidates(
            session, user_id=user_id, target_id=target_id, answer=answer
        )
        school_ids = [row.id for row in rows]
        await session.commit()

    return user_id, target_id, school_ids


async def test_schools_endpoints_round_trip(client) -> None:
    """候选院校能列出来，选定后目标院校被写回，归档后仍在列表里。"""

    _, target_id, school_ids = await _seed_via_client(client)

    listed = await client.get(f"/api/targets/{target_id}/schools")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == len(FAKE_SCHOOL_CANDIDATES)
    # 快照必须原样透出：优劣势是「当时是这么说的」，前端不得重新解释
    assert body[0]["snapshot"]["pros"]

    decided = await client.post(f"/api/targets/{target_id}/schools/{school_ids[0]}/decide")
    assert decided.status_code == 200
    assert decided.json()["status"] == "decided"

    target = await client.get(f"/api/targets/{target_id}")
    assert target.json()["target_school"] == body[0]["name"]

    archived = await client.post(f"/api/targets/{target_id}/schools/{school_ids[1]}/archive")
    assert archived.json()["status"] == "archived"

    still_there = await client.get(f"/api/targets/{target_id}/schools")
    assert len(still_there.json()) == len(FAKE_SCHOOL_CANDIDATES)


async def test_schools_endpoints_report_missing_target(client) -> None:
    assert (await client.get("/api/targets/999/schools")).status_code == 404
    assert (await client.post("/api/targets/999/schools/1/decide")).status_code == 404