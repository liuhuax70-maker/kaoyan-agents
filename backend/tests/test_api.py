"""接口层测试：用户、目标、计划、任务打卡、对话与系统总览。

覆盖完整业务闭环：创建用户 → 建目标 → 生成计划 → 打卡 → 看板。
"""

import json
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.timeutil import utc_today
from app.knowledge import Document, get_knowledge_base
from app.workflows.chat_agent import CHAT_AGENT_TASK
from tests.fakes import message_text, recorded_requests

TODAY = date.today()

UTC_TODAY = utc_today()
"""服务端的「今天」是 UTC 口径（``app.core.timeutil.utc_today``）。

凡是断言到「某一天」的用例都必须用它而不是本地 ``date.today()``：
服务器跑在 UTC、用户在东八区时，两者在凌晨会差一天，
顺着本地日期写断言就会在特定时段随机变红。
"""


def collect_references(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从对话响应中取出各智能体携带的知识库引用。"""

    return [
        reference
        for output in payload.get("outputs", [])
        for reference in (output.get("payload") or {}).get("references") or []
    ]


async def _create_user(client: AsyncClient, username: str = "xiaoyan") -> int:
    response = await client.post(
        "/api/users",
        json={
            "username": username,
            "nickname": "小研",
            "profile": {
                "base_level": "一般",
                "daily_hours": 5,
                "attention_span": 60,
                "self_discipline": 4,
                "preferred_slots": ["上午"],
            },
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def _create_target(client: AsyncClient, user_id: int) -> int:
    response = await client.post(
        "/api/targets",
        json={
            "user_id": user_id,
            "exam_type": "postgraduate",
            "title": "复旦计算机",
            "target_school": "复旦大学",
            "exam_date": (TODAY + timedelta(days=200)).isoformat(),
            "subjects": [
                {"name": "数学", "is_weak": True, "score_weight": 0.3},
                {"name": "英语", "score_weight": 0.2},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def test_create_and_read_user(client: AsyncClient) -> None:
    user_id = await _create_user(client)

    response = await client.get(f"/api/users/{user_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["nickname"] == "小研"
    assert body["profile"]["daily_hours"] == 5
    assert body["profile"]["preferred_slots"] == ["上午"]


async def test_chat_retrieval_toggle_controls_references(client: AsyncClient) -> None:
    """关闭检索时不应带出知识库引用，开启时应命中指定片段。

    用与提问完全相同的文本入库，保证相似度必然高于阈值——
    否则「关闭」断言会因为本来就没有命中而假通过。
    """

    message = "retrieval toggle probe alpha"
    user_id = await _create_user(client, username="retrieval_refs")

    await get_knowledge_base().ingest([Document(id="test::toggle", text=message)])

    off = await client.post(
        "/api/chat",
        json={"user_id": user_id, "message": message, "enable_retrieval": False},
    )
    assert off.status_code == 200
    assert collect_references(off.json()) == []

    on = await client.post(
        "/api/chat",
        json={"user_id": user_id, "message": message, "enable_retrieval": True},
    )
    assert on.status_code == 200
    references = collect_references(on.json())
    assert any(item["id"].startswith("test::toggle") for item in references)


async def test_lookup_user_by_username(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="lookup_target")

    found = await client.get("/api/users/lookup", params={"username": "lookup_target"})
    assert found.status_code == 200
    assert found.json()["id"] == user_id

    missing = await client.get("/api/users/lookup", params={"username": "nobody"})
    assert missing.status_code == 404


async def test_duplicate_username_returns_conflict(client: AsyncClient) -> None:
    await _create_user(client, username="duplicated")
    response = await client.post("/api/users", json={"username": "duplicated"})
    assert response.status_code == 409


async def test_update_profile(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="profile_update")

    response = await client.patch(
        f"/api/users/{user_id}",
        json={"nickname": "考研人", "profile": {"daily_hours": 8, "self_discipline": 5}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nickname"] == "考研人"
    assert body["profile"]["daily_hours"] == 8
    assert body["profile"]["self_discipline"] == 5


async def test_target_creation_marks_primary_and_keeps_subjects(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="target_owner")
    target_id = await _create_target(client, user_id)

    response = await client.get(f"/api/targets/{target_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["is_primary"] is True
    assert [item["name"] for item in body["subjects"]] == ["数学", "英语"]
    assert body["subjects"][0]["is_weak"] is True

    listing = await client.get("/api/targets", params={"user_id": user_id})
    assert len(listing.json()) == 1


async def test_missing_user_returns_not_found(client: AsyncClient) -> None:
    assert (await client.get("/api/users/999999")).status_code == 404

    chat = await client.post("/api/chat", json={"user_id": 999999, "message": "你好"})
    assert chat.status_code == 404


async def test_generate_plan_persists_plan_and_tasks(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="plan_owner")
    await _create_target(client, user_id)

    response = await client.post(
        "/api/plans/generate", json={"user_id": user_id, "goal": "数学冲刺 110 分"}
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["plan_id"] is not None
    assert body["conversation_id"]

    plan = await client.get(f"/api/plans/{body['plan_id']}")
    assert plan.status_code == 200

    detail = plan.json()
    assert detail["horizon_days"] > 0
    assert detail["stages"]
    assert sum(len(stage["tasks"]) for stage in detail["stages"]) > 0

    # 科目名要一直传到接口：课表的「今日目标」按科目汇总，取不到名就只能全归「其他」
    assert {task["subject"] for stage in detail["stages"] for task in stage["tasks"]} >= {"数学"}
    # 时段也必须在落库时补齐，否则课表的行是空的
    assert all(task["slot"] for stage in detail["stages"] for task in stage["tasks"])


async def test_chat_routes_to_tutor_and_keeps_conversation(client: AsyncClient) -> None:
    """路由到答疑讲师这条事实，现在由 ``tool_calls`` 承载。

    ``intent`` 是 Orchestrator 时代的字段，取的是首个工具的智能体标识 —— 与
    ``tool_calls[0]`` 恒等，因此已删除；断言改到权威来源上，测的还是同一件事。
    """

    user_id = await _create_user(client, username="chat_owner")
    await _create_target(client, user_id)

    first = await client.post(
        "/api/chat", json={"user_id": user_id, "message": "数学的极限为什么总是算不对"}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["tool_calls"], "答疑类提问应当调起子智能体"
    assert body["tool_calls"][0]["agent"] == "tutor"
    assert body["outputs"]
    assert body["reply"]

    second = await client.post(
        "/api/chat",
        json={
            "user_id": user_id,
            "message": "那我接下来该怎么安排复习",
            "conversation_id": body["conversation_id"],
        },
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == body["conversation_id"]

    detail = await client.get(f"/api/chat/conversations/{body['conversation_id']}")
    assert detail.status_code == 200
    assert detail.json()["message_count"] == 4


async def test_followup_chat_carries_previous_answer(client: AsyncClient) -> None:
    """阶段 2 验收：同一会话追问时，上一轮的问与答确实进了模型的输入。"""

    user_id = await _create_user(client, username="memory_owner")
    await _create_target(client, user_id)

    first = (
        await client.post(
            "/api/chat", json={"user_id": user_id, "message": "数学极限为什么算不对"}
        )
    ).json()
    assert first["reply"]

    second = await client.post(
        "/api/chat",
        json={
            "user_id": user_id,
            "message": "第二点再展开",
            "conversation_id": first["conversation_id"],
        },
    )
    assert second.status_code == 200, second.text

    messages = recorded_requests(CHAT_AGENT_TASK)[-1]
    contents = [message_text(item) for item in messages]
    # contents[0] 是 system，[1] 是上一轮提问，[2] 是上一轮回答，其后是本次追问
    assert "数学极限为什么算不对" in contents[1]
    assert contents[2] == first["reply"]
    assert any("第二点再展开" in text for text in contents[3:])


async def test_plan_generation_waits_for_confirmation(client: AsyncClient) -> None:
    """阶段 4 验收：生成计划后流程暂停，用户确认之前数据库里没有任何计划。"""

    user_id = await _create_user(client, username="confirm_owner")
    await _create_target(client, user_id)

    pending = await client.post(
        "/api/plans/generate", json={"user_id": user_id, "confirm_commit": True}
    )
    assert pending.status_code == 200, pending.text

    body = pending.json()
    assert body["plan_id"] is None, "还没确认就不该有 plan_id"
    assert body["reply"], "暂停也要先把聊天 Agent 的回答交给用户"

    confirmation = body["confirmation"]
    assert confirmation["kind"] == "plan_draft"
    assert confirmation["thread_id"], "没有 thread_id 就无从恢复"
    assert confirmation["items"], "用户要能逐条核对将要落库的计划"

    tasks = (await client.get("/api/tasks", params={"user_id": user_id})).json()
    assert tasks == [], "确认之前不应写入任何任务"

    conversation = (
        await client.get(f"/api/chat/conversations/{body['conversation_id']}")
    ).json()
    assert conversation["status"] == "awaiting_confirmation"

    confirmed = await client.post(
        "/api/chat/confirm",
        json={"conversation_id": body["conversation_id"], "approve": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["plan_id"] is not None
    assert confirmed.json()["confirmation"] is None
    assert "已确认" in confirmed.json()["reply"]

    assert (await client.get("/api/tasks", params={"user_id": user_id})).json()
    assert (
        await client.get(f"/api/chat/conversations/{body['conversation_id']}")
    ).json()["status"] == "active"


async def test_rejected_plan_is_never_written(client: AsyncClient) -> None:
    """驳回之后数据库保持原样，且同一个确认闸门不会二次放行。"""

    user_id = await _create_user(client, username="reject_owner")
    await _create_target(client, user_id)

    body = (
        await client.post(
            "/api/plans/generate", json={"user_id": user_id, "confirm_commit": True}
        )
    ).json()

    rejected = await client.post(
        "/api/chat/confirm",
        json={
            "conversation_id": body["conversation_id"],
            "approve": False,
            "feedback": "每天安排的时间太长",
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["plan_id"] is None
    assert "每天安排的时间太长" in rejected.json()["reply"]

    assert (await client.get("/api/tasks", params={"user_id": user_id})).json() == []

    again = await client.post(
        "/api/chat/confirm",
        json={"conversation_id": body["conversation_id"], "approve": True},
    )
    assert again.status_code == 404, "已经答复过的会话不应被重复恢复"


async def test_confirm_without_a_pending_plan_returns_not_found(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="no_pending")
    await _create_target(client, user_id)

    body = (
        await client.post(
            "/api/plans/generate", json={"user_id": user_id, "confirm_commit": True}
        )
    ).json()
    conversation_id = body["conversation_id"]

    # 先正常确认一次，闸门随之合上
    assert (
        await client.post(
            "/api/chat/confirm", json={"conversation_id": conversation_id, "approve": True}
        )
    ).status_code == 200

    missing = await client.post(
        "/api/chat/confirm", json={"conversation_id": conversation_id, "approve": True}
    )
    assert missing.status_code == 404
    assert (
        await client.post(
            "/api/chat/confirm", json={"conversation_id": 999999, "approve": True}
        )
    ).status_code == 404


async def test_stream_chat_stops_at_the_confirmation_gate(client: AsyncClient) -> None:
    """流式接口在确认闸门处收尾于 ``awaiting_confirmation``，而不是宣告 done。"""

    user_id = await _create_user(client, username="stream_confirm")
    await _create_target(client, user_id)

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"user_id": user_id, "message": "帮我制定学习计划：数学冲刺", "confirm_commit": True},
    ) as response:
        assert response.status_code == 200
        lines = [chunk async for chunk in response.aiter_lines()]

    frames = [json.loads(line[len("data: ") :]) for line in lines if line.startswith("data: ")]
    assert [frame["type"] for frame in frames if frame["type"] == "token"], "回答仍要逐字到达"
    assert frames[-1]["type"] == "awaiting_confirmation"
    assert not any(frame["type"] == "done" for frame in frames)
    assert frames[-1]["confirmation"]["thread_id"]

    assert (await client.get("/api/tasks", params={"user_id": user_id})).json() == []


async def test_task_check_in_updates_status_and_streak(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="task_owner")
    await _create_target(client, user_id)
    plan = (
        await client.post("/api/plans/generate", json={"user_id": user_id})
    ).json()

    tasks = (await client.get("/api/tasks", params={"user_id": user_id})).json()
    assert tasks

    task_id = tasks[0]["id"]
    response = await client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "done", "actual_minutes": 75, "score": 88, "note": "极限计算仍有失误"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"

    progress = (await client.get(f"/api/tasks/{task_id}/progress")).json()
    assert len(progress) == 1
    assert progress[0]["actual_minutes"] == 75
    assert progress[0]["score"] == 88
    assert progress[0]["note"] == "极限计算仍有失误"

    dashboard = (await client.get("/api/dashboard", params={"user_id": user_id})).json()
    assert dashboard["task_stats"]["done"] >= 1
    assert dashboard["plan_id"] == plan["plan_id"]
    assert dashboard["plan_progress"] > 0


async def test_task_filter_by_status(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="filter_owner")
    await _create_target(client, user_id)
    await client.post("/api/plans/generate", json={"user_id": user_id})

    todo = (await client.get("/api/tasks", params={"user_id": user_id, "status": "todo"})).json()
    done = (await client.get("/api/tasks", params={"user_id": user_id, "status": "done"})).json()

    assert todo
    assert done == []
    assert (await client.patch("/api/tasks/999999", json={"status": "done"})).status_code == 404


async def test_stream_chat_emits_events(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="stream_owner")
    await _create_target(client, user_id)

    async with client.stream(
        "POST", "/api/chat/stream", json={"user_id": user_id, "message": "帮我复盘一下复习进度"}
    ) as response:
        assert response.status_code == 200
        payload = "".join([chunk async for chunk in response.aiter_text()])

    assert '"type": "start"' in payload
    assert '"type": "output"' in payload
    assert '"type": "done"' in payload


async def test_stream_chat_emits_incremental_tokens(client: AsyncClient) -> None:
    """阶段 3 验收：回答逐字到达，而不是攒到最后一次性出现。"""

    user_id = await _create_user(client, username="token_owner")
    await _create_target(client, user_id)

    async with client.stream(
        "POST", "/api/chat/stream", json={"user_id": user_id, "message": "数学极限为什么算不对"}
    ) as response:
        lines = [chunk async for chunk in response.aiter_lines()]

    frames = [
        json.loads(line[len("data: ") :])
        for line in lines
        if line.startswith("data: ")
    ]
    tokens = [frame["text"] for frame in frames if frame["type"] == "token"]
    done = frames[-1]

    # 连续多帧增量，且拼起来正好等于最终回答——不是「一次性 done」
    assert len(tokens) > 1
    assert "".join(tokens) == done["reply"]

    # token 帧出现在 done 之前，用户看到的才是「边生成边显示」
    assert frames[-1]["type"] == "done"

    # 调用链由后端直接给出结构化帧，前端不必再拿事件里的 node 名去猜
    calls = [frame for frame in frames if frame["type"] == "tool_call"]
    assert calls, "答疑类提问应当在流里能看到子智能体被调起"
    assert calls[0]["agent"] == "tutor"
    assert calls[0]["label"]


async def test_reminder_run_endpoint(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="reminder_owner")
    await _create_target(client, user_id)
    await client.post("/api/plans/generate", json={"user_id": user_id})

    response = await client.post("/api/reminders/run", params={"kind": "weekly"})
    assert response.status_code == 200

    body = response.json()
    assert body["kind"] == "weekly"
    assert body["generated"] == 1

    listed = (await client.get("/api/reminders", params={"user_id": user_id})).json()
    assert len(listed) == 1
    assert listed[0]["reminder_type"] == "weekly"

    assert (
        await client.post("/api/reminders/run", params={"kind": "unknown"})
    ).status_code == 400


async def test_overview_exposes_roles_and_workflow(client: AsyncClient) -> None:
    response = await client.get("/api/overview")
    assert response.status_code == 200

    body = response.json()
    role_keys = {item["key"] for item in body["roles"]}
    assert {"chat_agent", "planner", "plan_editor"} <= role_keys
    assert {item["role_name"] for item in body["prompts"]} >= {"备考规划师", "复盘诊断师"}

    workflow = body["workflow"]
    assert workflow["entry"] == "prepare_context"
    assert workflow["pattern"] == "subagents"
    assert "chat_agent" in workflow["nodes"]
    assert {item["name"] for item in workflow["tools"]} >= {"generate_plan", "revise_plan"}

    names = {item["name"] for item in body["schedule"]}
    assert names == {
        "daily-reminder",
        "overdue-nudge",
        "idle-warning",
        "weekly-digest",
        "school-brief",
    }
    assert body["capability"]["llm_provider"] == "ollama"


async def test_knowledge_endpoints(client: AsyncClient) -> None:
    stats = await client.get("/api/knowledge/stats")
    assert stats.status_code == 200
    assert stats.json()["dimension"] > 0

    ingested = await client.post("/api/knowledge/ingest", json={"reset": True})
    assert ingested.status_code == 200
    assert ingested.json()["chunks"] > 0

    hits = await client.post(
        "/api/knowledge/search", json={"query": "英语真题怎么刷", "top_k": 3}
    )
    assert hits.status_code == 200
    assert hits.json()
    assert hits.json()[0]["score"] > 0


@pytest.mark.parametrize("path", ["/api/health", "/api/overview"])
async def test_system_endpoints_are_reachable(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 200


async def test_plan_task_crud_via_api(client: AsyncClient) -> None:
    """用户可以在计划表里直接增删改任务，与聊天改计划走同一套底层逻辑。"""

    user_id = await _create_user(client, username="manual_editor")
    await _create_target(client, user_id)

    generated = await client.post("/api/plans/generate", json={"user_id": user_id})
    assert generated.status_code == 200
    plan_id = generated.json()["plan_id"]
    assert plan_id

    created = await client.post(
        f"/api/plans/{plan_id}/tasks",
        json={
            "title": "手动补充：英语长难句 10 句",
            "description": "逐句拆结构并翻译",
            "subject": "英语",
            "duration_minutes": 45,
            "priority": "high",
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["status"] == "todo"

    updated = await client.patch(
        f"/api/tasks/{task_id}",
        json={"title": "手动补充：英语长难句 20 句", "duration_minutes": 60},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "手动补充：英语长难句 20 句"
    assert updated.json()["duration_minutes"] == 60

    renamed = await client.patch(
        f"/api/plans/{plan_id}", json={"title": "冲刺计划（已人工调整）"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "冲刺计划（已人工调整）"

    deleted = await client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/tasks/{task_id}")).status_code == 404


async def test_slot_ordering_uses_natural_slot_order(client: AsyncClient) -> None:
    """课表排序按 上午→下午→晚上，而不是中文字典序。

    三个任务按 晚上/上午/下午 的顺序创建，``order_index`` 依次为 0/1/2。
    排序若只看日期与 ``order_index``，返回的就是创建顺序；只有时段参与了排序，
    才会变成 上午→下午→晚上 —— 这正是 CASE 助手存在的理由（Unicode 序不是时间序）。
    """

    user_id = await _create_user(client, username="slot_order")
    await _create_target(client, user_id)

    generated = await client.post("/api/plans/generate", json={"user_id": user_id})
    assert generated.status_code == 200, generated.text
    plan_id = generated.json()["plan_id"]

    mine = {f"{slot}任务" for slot in ("晚上", "上午", "下午")}
    for slot in ("晚上", "上午", "下午"):
        created = await client.post(
            f"/api/plans/{plan_id}/tasks",
            json={
                "title": f"{slot}任务",
                "planned_date": TODAY.isoformat(),
                "slot": slot,
                "duration_minutes": 30,
            },
        )
        assert created.status_code == 201, created.text

    listing = await client.get("/api/tasks", params={"user_id": user_id, "plan_id": plan_id})
    assert listing.status_code == 200
    ordered = [item["slot"] for item in listing.json() if item["title"] in mine]

    assert ordered == ["上午", "下午", "晚上"]


async def test_defer_api_endpoint(client: AsyncClient) -> None:
    """一键顺延把逾期任务挪到今天，并如实返回挪了几条。"""

    user_id = await _create_user(client, username="defer_user")
    await _create_target(client, user_id)

    generated = await client.post("/api/plans/generate", json={"user_id": user_id})
    assert generated.status_code == 200, generated.text
    plan_id = generated.json()["plan_id"]

    created = await client.post(
        f"/api/plans/{plan_id}/tasks",
        json={
            "title": "前天的数学错题",
            "planned_date": (UTC_TODAY - timedelta(days=3)).isoformat(),
            "duration_minutes": 30,
        },
    )
    assert created.status_code == 201, created.text

    response = await client.post(f"/api/plans/{plan_id}/defer", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_date"] == UTC_TODAY.isoformat()
    # 生成计划的任务都排在今天及以后，因此只有手动建的那一条算逾期
    assert body["moved"] == 1

    listing = await client.get(
        "/api/tasks", params={"user_id": user_id, "plan_id": plan_id}
    )
    tasks = listing.json()
    assert all(item["planned_date"] >= UTC_TODAY.isoformat() for item in tasks)
    deferred = [item for item in tasks if item["title"] == "前天的数学错题"]
    assert deferred and deferred[0]["planned_date"] == UTC_TODAY.isoformat()


async def test_chat_defer_request_uses_the_same_path(client: AsyncClient) -> None:
    """聊天里说「把没做完的顺延到明天」，与按钮走的是同一条顺延路径。"""

    user_id = await _create_user(client, username="defer_chat")
    await _create_target(client, user_id)

    generated = await client.post("/api/plans/generate", json={"user_id": user_id})
    plan_id = generated.json()["plan_id"]

    await client.post(
        f"/api/plans/{plan_id}/tasks",
        json={
            "title": "前天的政治背诵",
            "planned_date": (UTC_TODAY - timedelta(days=2)).isoformat(),
            "duration_minutes": 30,
        },
    )

    reply = await client.post(
        "/api/chat", json={"user_id": user_id, "message": "把没做完的顺延到明天"}
    )
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert "revise_plan" in {item["name"] for item in payload["tool_calls"]}

    listing = await client.get(
        "/api/tasks", params={"user_id": user_id, "plan_id": plan_id}
    )
    deferred = [item for item in listing.json() if item["title"] == "前天的政治背诵"]
    assert deferred
    # 「明天」是相对今天的一天，而不是相对计划开始日 —— 模型看不见今天是几号
    assert deferred[0]["planned_date"] == (UTC_TODAY + timedelta(days=1)).isoformat()


async def test_chat_revision_is_persisted(client: AsyncClient) -> None:
    """聊天里让计划修订师改计划，改动必须真正落库。"""

    user_id = await _create_user(client, username="revise_user")
    await _create_target(client, user_id)

    plan_id = (
        await client.post("/api/plans/generate", json={"user_id": user_id})
    ).json()["plan_id"]

    before = (await client.get(f"/api/plans/{plan_id}")).json()
    before_dates = {
        task["title"]: task["planned_date"]
        for stage in before["stages"]
        for task in stage["tasks"]
    }
    assert before_dates

    reply = await client.post(
        "/api/chat",
        json={"user_id": user_id, "message": "把没做完的任务往后挪三天"},
    )
    assert reply.status_code == 200
    payload = reply.json()

    assert payload["plan_id"] == plan_id
    assert "revise_plan" in {item["name"] for item in payload["tool_calls"]}
    assert payload["reply"].strip()

    after = (await client.get(f"/api/plans/{plan_id}")).json()
    after_dates = {
        task["title"]: task["planned_date"]
        for stage in after["stages"]
        for task in stage["tasks"]
    }
    moved = [title for title, value in after_dates.items() if before_dates.get(title) != value]
    assert moved, "计划修订没有真正落库"