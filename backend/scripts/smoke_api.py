"""端到端冒烟测试。

按真实用户路径依次调用接口，验证部署后的服务链路完整可用：

    建账号 → 设备考目标 → 生成学习计划（LangGraph 多智能体工作流）
    → 对话问答 → 任务打卡 → 触发提醒督促 → 校验向量库检索

用法（需应用已启动）：

    python -m scripts.smoke_api
    python -m scripts.smoke_api --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date, timedelta

import httpx

TODAY = date.today()


class SmokeFailure(RuntimeError):
    """冒烟测试断言失败。"""


def check(condition: bool, message: str) -> None:
    """断言，失败即中断。"""

    if not condition:
        raise SmokeFailure(message)
    print(f"[OK]   {message}")


async def run(base_url: str) -> int:
    """执行全部步骤并返回进程退出码。"""

    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=base_url, timeout=180.0) as client:
        # 1. 健康检查
        health = (await client.get("/api/health")).json()
        check(health["status"] == "ok", "健康检查通过（db/redis/vector 均可用）")

        # 2. 建立考生账号
        username = f"smoke_{suffix}"
        user = (
            await client.post(
                "/api/users",
                json={
                    "username": username,
                    "nickname": "冒烟考生",
                    "profile": {
                        "education": "本科大三",
                        "major": "计算机",
                        "base_level": "一般",
                        "daily_hours": 5,
                        "weekly_days": 6,
                        "attention_span": 50,
                        "self_discipline": 3,
                        "preferred_slots": ["上午", "晚上"],
                        "notes": "数学基础薄弱",
                    },
                },
            )
        ).json()
        user_id = user["id"]
        check(user_id > 0, f"创建考生成功（id={user_id} username={username}）")

        # 用户名可反查，支撑前端登录
        found = await client.get("/api/users/lookup", params={"username": username})
        check(found.status_code == 200, "按用户名反查账号成功")

        # 3. 设备考目标与科目
        target = (
            await client.post(
                "/api/targets",
                json={
                    "user_id": user_id,
                    "title": "计算机考研 408",
                    "target_school": "目标院校",
                    "target_major": "计算机科学与技术",
                    "exam_date": (TODAY + timedelta(days=150)).isoformat(),
                    "description": "目标总分 380",
                    "subjects": [
                        {"name": "政治", "score_weight": 0.2},
                        {"name": "英语", "score_weight": 0.2},
                        {"name": "数学", "score_weight": 0.3, "is_weak": True},
                        {"name": "专业课", "score_weight": 0.3},
                    ],
                },
            )
        ).json()
        check(len(target["subjects"]) == 4, "创建备考目标成功（4 门科目）")

        # 4. 生成学习计划：走完整多智能体工作流
        plan_result = (
            await client.post(
                "/api/plans/generate",
                json={"user_id": user_id, "goal": "数学重点突破", "enable_review": True},
            )
        ).json()
        plan_id = plan_result.get("plan_id")
        check(bool(plan_id), f"生成学习计划成功（plan_id={plan_id}）")
        check(
            len(plan_result.get("outputs", [])) > 0,
            f"工作流产出 {len(plan_result.get('outputs', []))} 个智能体结果"
            f"（agents={plan_result.get('agents')}）",
        )

        # 5. 计划落库后可查到阶段与任务
        plan = (await client.get(f"/api/plans/{plan_id}")).json()
        stages = plan["stages"]
        tasks = [task for stage in stages for task in stage["tasks"]]
        check(len(stages) > 0, f"计划已持久化（{len(stages)} 个阶段 / {len(tasks)} 个任务）")
        check(len(tasks) > 0, "任务拆解结果非空")

        # 6. 对话问答
        chat = (
            await client.post(
                "/api/chat",
                json={
                    "user_id": user_id,
                    "message": "数学复习该怎么安排？",
                    "conversation_id": None,
                },
            )
        ).json()
        check(bool(chat.get("reply") or chat.get("outputs")), "对话问答返回结果")

        # 7. 计划版本：同一目标下只应有一个生效计划
        plans = (await client.get("/api/plans", params={"user_id": user_id})).json()
        active = [item for item in plans if item["status"] == "active"]
        check(len(active) == 1, f"同一目标仅有一个生效计划（共 {len(plans)} 个版本）")
        check(
            active[0]["version"] == len(plans),
            f"计划版本号随重规划递增（当前 v{active[0]['version']}）",
        )
        current_tasks = [task for stage in active[0]["stages"] for task in stage["tasks"]]
        check(len(current_tasks) > 0, f"当前生效计划含 {len(current_tasks)} 个任务")

        # 8. 任务打卡
        first_task = current_tasks[0]
        updated = (
            await client.patch(
                f"/api/tasks/{first_task['id']}",
                json={"status": "done", "actual_minutes": first_task["duration_minutes"]},
            )
        ).json()
        check(updated["status"] == "done", f"任务打卡成功（task_id={first_task['id']}）")

        # 9. 看板统计只覆盖当前生效计划，不应被历史版本稀释
        board = (await client.get("/api/dashboard", params={"user_id": user_id})).json()
        check(
            board["task_stats"]["total"] == len(current_tasks),
            f"看板任务总数仅统计当前计划（{board['task_stats']['total']} 个）",
        )
        check(board["task_stats"]["done"] == 1, "看板完成数与实际打卡一致（1 个）")

        # 9. 触发提醒督促（经 Celery worker 执行）
        reminder = (
            await client.post("/api/reminders/run", params={"kind": "daily"})
        ).json()
        check(isinstance(reminder, dict), f"提醒任务触发成功（{reminder}）")

        # 10. 知识库检索
        stats = (await client.get("/api/knowledge/stats")).json()
        check(stats["chunks"] > 0, f"知识库已就绪（{stats['backend']} / {stats['chunks']} 个片段）")

        hits = (
            await client.post("/api/knowledge/search", json={"query": "数学怎么提分", "top_k": 3})
        ).json()
        check(len(hits) > 0, f"知识库检索命中 {len(hits)} 条")

        # 11. 系统能力自省接口（供运维排查，不参与前端页面）
        overview = (await client.get("/api/overview")).json()
        check(
            len(overview["roles"]) >= 5 and len(overview["prompts"]) >= 5,
            f"系统能力接口可用（{len(overview['roles'])} 个角色 / "
            f"{len(overview['prompts'])} 个提示词任务）",
        )

    return 0


async def main() -> int:
    """解析参数、执行冒烟并输出结论。"""

    parser = argparse.ArgumentParser(description="考研智能体系统端到端冒烟测试")
    parser.add_argument("--base-url", default="http://localhost:8000", help="后端地址")
    args = parser.parse_args()

    print("=" * 64)
    print(f"考研智能体系统 · 端到端冒烟测试 @ {args.base_url}")
    print("=" * 64)

    try:
        code = await run(args.base_url)
    except SmokeFailure as exc:
        print("-" * 64)
        print(f"[FAIL] {exc}")
        return 1
    except httpx.HTTPStatusError as exc:
        print("-" * 64)
        print(f"[FAIL] 接口返回 {exc.response.status_code}：{exc.response.text[:400]}")
        return 1
    except Exception as exc:  # noqa: BLE001 - 冒烟脚本需要暴露完整原因
        print("-" * 64)
        print(f"[FAIL] 未预期异常：{exc!r}")
        return 1

    print("-" * 64)
    print("全部步骤通过。")
    return code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
