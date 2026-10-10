"""接口层测试：用户、目标、计划、任务打卡、对话与系统总览。

覆盖完整业务闭环：创建用户 → 建目标 → 生成计划 → 打卡 → 看板。
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

TODAY = date.today()


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


async def test_chat_routes_intent_and_keeps_conversation(client: AsyncClient) -> None:
    user_id = await _create_user(client, username="chat_owner")
    await _create_target(client, user_id)

    first = await client.post(
        "/api/chat", json={"user_id": user_id, "message": "数学的极限为什么总是算不对"}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["intent"] == "tutor"
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
    assert len(body["roles"]) == 7
    assert {item["role_name"] for item in body["prompts"]} >= {"备考规划师", "复盘诊断师"}
    assert body["workflow"]["entry"] == "prepare_context"
    assert len(body["schedule"]) == 4
    assert body["capability"]["llm_provider"] == "stub"


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
