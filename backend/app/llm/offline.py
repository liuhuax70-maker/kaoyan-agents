"""离线兜底内容生成。

在未配置大模型密钥、或模型调用失败时，仍要保证全流程可跑通，
因此为每个任务提供确定性的结构化内容生成器。
生成结果同样会经过 Pydantic 校验，与真实模型输出走同一条路径。
"""

from collections.abc import Callable
from typing import Any

PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]]

DEFAULT_SUBJECTS = ("政治", "英语", "数学", "专业课")

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "plan": ("计划", "规划", "安排", "时间表", "怎么复习", "如何复习", "备考", "冲刺", "从哪开始"),
    "breakdown": ("拆解", "拆分", "细化", "每天做什么", "每日任务", "任务分配"),
    "tutor": ("为什么", "怎么理解", "讲解", "不懂", "不会", "这道题", "公式", "原理", "推导"),
    "review": ("复盘", "总结", "诊断", "进度", "落后", "焦虑", "来得及", "效率", "完成度", "状态"),
    "resource": ("资料", "书单", "教材", "真题", "题库", "用什么书", "网课", "讲义"),
    "nudge": ("提醒", "督促", "坚持不下去", "打卡", "断签", "没动力"),
}

INTENT_AGENTS: dict[str, list[str]] = {
    "plan": ["planner", "breakdown"],
    "breakdown": ["breakdown"],
    "tutor": ["tutor"],
    "review": ["reviewer"],
    "resource": ["resource"],
    "nudge": ["coach"],
    "chat": ["tutor"],
}

SUBJECT_PLAYBOOK: dict[str, dict[str, str]] = {
    "政治": {
        "core": "精讲教材 + 章节思维导图",
        "drill": "章节配套选择题（1000 题量级）",
        "final": "冲刺背诵手册 + 时政专题",
        "usage": "前期只做选择题，主观题从强化阶段起滚动背诵，每天固定 30 分钟。",
    },
    "英语": {
        "core": "大纲词汇书 + 长难句解析",
        "drill": "近 15 年真题阅读（精读并逐句翻译）",
        "final": "作文模板 + 高频词组清单",
        "usage": "真题按套限时训练，第一遍不限时吃透，第二遍限时，第三遍只看错题。",
    },
    "数学": {
        "core": "教材 + 基础讲义（含例题推导）",
        "drill": "强化讲义配套习题 + 分题型题库",
        "final": "真题套卷 + 按考点归类的错题本",
        "usage": "先保证计算准确率再追速度，每道错题记录卡住的那一步。",
    },
    "专业课": {
        "core": "指定参考书 + 章节框架笔记",
        "drill": "目标院校历年真题（含回忆版）",
        "final": "院校重点专题 + 答题模板",
        "usage": "对齐目标院校考纲，优先吃透反复出现的考点。",
    },
}

DEFAULT_PLAYBOOK = {
    "core": "考纲 + 权威教材",
    "drill": "历年真题与专项练习",
    "final": "高频考点清单与错题本",
    "usage": "选定一套主资料做透，比频繁更换资料更有效。",
}


def _subjects(context: dict[str, Any]) -> list[str]:
    raw = context.get("subjects") or []
    names = [str(item) for item in raw if str(item).strip()]
    return names or list(DEFAULT_SUBJECTS)


def _weak_subjects(context: dict[str, Any]) -> set[str]:
    return {str(item) for item in (context.get("weak_subjects") or [])}


def _stage_plan(days: int) -> list[tuple[str, str, float, float, str]]:
    """按总天数给出阶段划分。"""

    if days < 60:
        return [
            ("基础强化", "foundation", 0.0, 0.5, "打牢基础并完成第一轮专题训练"),
            ("真题冲刺", "sprint", 0.5, 0.85, "成套真题限时训练并按考点回炉"),
            ("模考复盘", "mock", 0.85, 1.0, "全真模考与错题集中回炉"),
        ]
    return [
        ("基础夯实", "foundation", 0.0, 0.4, "通读教材与考纲，建立知识框架"),
        ("强化提升", "enhancement", 0.4, 0.7, "专题突破与题型归纳"),
        ("真题冲刺", "sprint", 0.7, 0.9, "成套真题限时训练"),
        ("模考复盘", "mock", 0.9, 1.0, "全真模考保持手感并压缩背诵清单"),
    ]


def build_intent(context: dict[str, Any]) -> dict[str, Any]:
    """按关键词判定意图，作为调度协调者的离线实现。"""

    request = str(context.get("request", "")).lower()
    scores = {
        intent: sum(1 for word in words if word in request)
        for intent, words in INTENT_KEYWORDS.items()
    }
    best = max(scores, key=lambda key: scores[key])
    hits = scores[best]

    if hits == 0:
        return {
            "intent": "chat",
            "confidence": 0.4,
            "agents": INTENT_AGENTS["chat"],
            "reason": "未命中明确意图关键词，先按答疑处理并追问补充信息",
        }

    total = sum(scores.values()) or 1
    return {
        "intent": best,
        "confidence": round(min(0.55 + hits * 0.15, 0.95), 2),
        "agents": INTENT_AGENTS[best],
        "reason": f"命中「{best}」相关关键词 {hits} 个，在全部候选中占比 {hits / total:.0%}",
    }


def build_plan_draft(context: dict[str, Any]) -> dict[str, Any]:
    """生成分阶段学习计划草稿。"""

    subjects = _subjects(context)
    weak = _weak_subjects(context)
    days = max(int(context.get("days_left") or 120), 21)
    daily_hours = float(context.get("daily_hours") or 4)
    attention = int(context.get("attention_span") or 50)
    focus_minutes = max(30, min(attention, 120))

    stages: list[dict[str, Any]] = []
    for name, stage_type, start_ratio, end_ratio, focus in _stage_plan(days):
        start = round(days * start_ratio)
        end = max(start + 1, round(days * end_ratio))
        tasks: list[dict[str, Any]] = []

        for offset, subject in enumerate(subjects):
            day = min(start + offset, end)
            is_weak = subject in weak
            tasks.append(
                {
                    "title": f"{subject}｜{focus}",
                    "description": (
                        f"完成 {subject}「{name}」阶段核心内容，产出章节笔记与错题记录，"
                        f"阶段末能独立完成对应题型 10 题且正确率不低于 80%"
                    ),
                    "task_type": "practice" if stage_type in {"sprint", "mock"} else "learn",
                    "subject": subject,
                    "day_offset": day,
                    "duration_minutes": focus_minutes,
                    "priority": "high" if is_weak else "medium",
                    "difficulty": 4 if is_weak else 3,
                    "resource_hint": SUBJECT_PLAYBOOK.get(subject, DEFAULT_PLAYBOOK)["core"],
                    "depends_on_index": None,
                }
            )

        tasks.append(
            {
                "title": f"{name}阶段复盘：错题归档与知识缺口梳理",
                "description": "汇总本阶段错题并按考点归类，列出仍未掌握的知识点清单",
                "task_type": "review",
                "subject": "综合",
                "day_offset": end,
                "duration_minutes": max(30, focus_minutes),
                "priority": "high",
                "difficulty": 2,
                "resource_hint": "错题本 + 知识框架笔记",
                "depends_on_index": None,
            }
        )

        stages.append(
            {
                "name": name,
                "stage_type": stage_type,
                "focus": focus,
                "start_offset": start,
                "end_offset": end,
                "target_hours": round(daily_hours * max(end - start, 1) * 0.85, 1),
                "tasks": tasks,
            }
        )

    notes = [
        f"按每日 {daily_hours:g} 小时的投入排布，单次任务控制在 {focus_minutes} 分钟以内",
        "每阶段结束前必须完成一次错题归档，避免问题累积",
    ]
    if weak:
        notes.append(f"薄弱科目（{'、'.join(sorted(weak))}）已提升优先级，安排在高精力时段")
    if not context.get("days_left"):
        notes.append("档案中缺少考试日期，当前按 120 天通用节奏排布")

    return {
        "title": f"{days} 天{'｜'.join(subjects[:2])}备考计划",
        "goal": f"在 {days} 天内完成 {len(subjects)} 门科目的系统备考并进入模考状态",
        "strategy": (
            f"以 {'、'.join(subjects)} 为主线，按阶段滚动推进；"
            f"每周预留一天用于整卷训练与复盘，薄弱科目优先占用高精力时段。"
        ),
        "horizon_days": days,
        "daily_hours": daily_hours,
        "stages": stages,
        "notes": notes,
    }


def build_task_breakdown(context: dict[str, Any]) -> dict[str, Any]:
    """把阶段目标拆解为可打卡任务。"""

    subjects = _subjects(context)
    weak = _weak_subjects(context)
    scope = str(context.get("scope") or "当前阶段")
    attention = int(context.get("attention_span") or 50)
    block = max(30, min(attention, 90))

    tasks: list[dict[str, Any]] = []
    for day, subject in enumerate(subjects):
        is_weak = subject in weak
        tasks.append(
            {
                "title": f"{subject}：{scope}核心内容精读",
                "description": f"精读 {subject} 对应章节并整理提纲，完成课后基础题 15 道",
                "task_type": "learn",
                "subject": subject,
                "day_offset": day,
                "duration_minutes": block,
                "priority": "high" if is_weak else "medium",
                "difficulty": 4 if is_weak else 3,
                "resource_hint": SUBJECT_PLAYBOOK.get(subject, DEFAULT_PLAYBOOK)["core"],
                "depends_on_index": None,
            }
        )
        tasks.append(
            {
                "title": f"{subject}：{scope}配套习题训练",
                "description": "完成对应专项练习 20 题，错题当天归因并记录卡点步骤",
                "task_type": "practice",
                "subject": subject,
                "day_offset": day,
                "duration_minutes": block,
                "priority": "medium",
                "difficulty": 3,
                "resource_hint": SUBJECT_PLAYBOOK.get(subject, DEFAULT_PLAYBOOK)["drill"],
                "depends_on_index": len(tasks) - 1,
            }
        )

    return {
        "scope": scope,
        "summary": f"围绕 {scope} 拆出 {len(tasks)} 个可在 30-90 分钟内完成的任务",
        "tasks": tasks,
        "notes": [
            "同一天同一科目不超过 2 个高难度任务",
            "任务完成后立即记录实际耗时，便于后续校准排期",
        ],
    }


def build_tutoring(context: dict[str, Any]) -> dict[str, Any]:
    """生成知识点讲解与解题路径。"""

    request = str(context.get("request") or "").strip()
    subject = str(context.get("subject") or "通用")
    summary = request if len(request) <= 120 else request[:120] + "…"

    return {
        "subject": subject,
        "question_summary": summary or "考生提出了一个知识点问题，但未提供完整题干",
        "key_points": [
            "先明确题目考查的定义、公式与其成立条件",
            "区分题型特征，判断应使用哪一套标准解法",
            "记住该题型的边界情况，避免套用公式时忽略前提",
        ],
        "steps": [
            "审题定位：圈出已知条件与所求量，明确考查的知识点",
            "回归定义：把条件翻译成教材中的定义或公式，确认适用前提成立",
            "分步推导：拆成 2 到 3 个可独立验证的小步骤，逐步推进并标注依据",
            "结果校验：用特殊值或边界情况回代，检查答案是否合理",
        ],
        "pitfalls": [
            "只记住结论而忽略公式成立条件，条件不满足时仍然套用",
            "跳步推导，导致中间环节的错误无法被察觉",
            "做完不校验，无法发现量纲或边界上的明显错误",
        ],
        "followups": [
            "这个知识点对应的定义你能不看书写出来吗？",
            "如果把题干条件替换其中一个，结论还成立吗？",
            "同类题你能独立完成几道？错因分别是什么？",
        ],
        "related_practice": [
            "找 3 道同类型基础题，限时完成并标注每步依据",
            "整理该题型近三年的真题出题角度",
        ],
    }


def build_diagnosis(context: dict[str, Any]) -> dict[str, Any]:
    """生成备考复盘诊断报告。"""

    completion = float(context.get("completion_rate") or 0)
    total = int(context.get("total_tasks") or 0)
    done = int(context.get("done_tasks") or 0)
    overdue = int(context.get("overdue_count") or 0)
    idle_days = int(context.get("idle_days") or 0)
    days_left = context.get("days_left")
    subjects = _subjects(context)
    weak = _weak_subjects(context)

    findings = [
        f"当前共 {total} 个任务，已完成 {done} 个，整体完成率 {completion:.0%}",
        f"逾期任务 {overdue} 个，近 7 天学习时长 {int(context.get('recent_minutes') or 0)} 分钟",
    ]
    if days_left is not None:
        findings.append(f"距离考试还有 {days_left} 天，剩余任务需按周重新配速")
    if subjects:
        findings.append(f"当前覆盖 {len(subjects)} 门科目，薄弱科目 {len(weak)} 门")

    risks: list[dict[str, Any]] = []
    if completion < 0.3:
        risks.append(
            {
                "level": "high",
                "title": "任务完成率偏低",
                "detail": f"完成率仅 {completion:.0%}，且逾期 {overdue} 个",
                "suggestion": "把单个任务压缩到 60 分钟以内，每天只保底完成 2 个任务",
            }
        )
    if idle_days >= 3:
        risks.append(
            {
                "level": "high",
                "title": "出现连续断签",
                "detail": f"已连续 {idle_days} 天没有完成任何任务",
                "suggestion": "今天只安排 1 个 30 分钟任务恢复手感，不要直接加码",
            }
        )
    if days_left is not None and days_left <= 60:
        risks.append(
            {
                "level": "medium",
                "title": "进入冲刺期",
                "detail": f"剩余 {days_left} 天，新知识输入窗口已经很窄",
                "suggestion": "把时间切换到真题与错题回炉，停止大面积刷新资料",
            }
        )
    if not risks:
        risks.append(
            {
                "level": "low",
                "title": "暂无明显风险",
                "detail": "完成率与节奏均处于合理区间",
                "suggestion": "保持当前节奏，每周固定做一次整卷训练检验效果",
            }
        )

    if completion >= 0.8:
        discipline = 5
    elif completion >= 0.6:
        discipline = 4
    elif completion >= 0.4:
        discipline = 3
    else:
        discipline = 2

    return {
        "summary": (
            f"整体完成率 {completion:.0%}，执行稳定性评分 {discipline}/5，"
            "需重点关注逾期任务"
        ),
        "completion_rate": min(max(completion, 0.0), 1.0),
        "discipline_score": discipline,
        "findings": findings,
        "risks": risks,
        "adjustments": [
            "把每天最清醒的 2 小时锁定给薄弱科目，做深度练习而不是刷题",
            "逾期任务统一重排到未来 3 天，按优先级从高到低处理",
            "本周安排一次整卷训练，用得分率而不是做题量衡量进度",
        ],
        "encouragement": (
            f"你已经完成 {done} 个任务，把逾期项清掉就能回到正轨。"
            if done
            else "先把今天的一个小任务完成，节奏比强度更重要。"
        ),
    }


def build_resource_plan(context: dict[str, Any]) -> dict[str, Any]:
    """生成资料组合建议。"""

    subjects = _subjects(context)
    weak = _weak_subjects(context)
    items: list[dict[str, Any]] = []

    for subject in subjects:
        book = SUBJECT_PLAYBOOK.get(subject, DEFAULT_PLAYBOOK)
        rank = 1 if subject in weak else 2
        items.append(
            {
                "subject": subject,
                "stage": "基础",
                "name": book["core"],
                "usage": book["usage"],
                "priority": rank,
            }
        )
        items.append(
            {
                "subject": subject,
                "stage": "强化",
                "name": book["drill"],
                "usage": "按题型成组训练，做完立刻归因，错题当天进入错题本",
                "priority": rank,
            }
        )
        items.append(
            {
                "subject": subject,
                "stage": "冲刺",
                "name": book["final"],
                "usage": "限时套卷训练，压缩到高频考点与易错清单",
                "priority": 2,
            }
        )

    return {
        "summary": f"覆盖 {len(subjects)} 门科目，按基础、强化、冲刺三阶段给出资料组合",
        "items": items,
        "tips": [
            "同一科目同一阶段只保留一套主资料，其余仅作补充",
            "真题优先于模拟题，院校真题优先于通用题库",
            "资料必须配错题本，否则等于没做",
        ],
    }


def build_nudge(context: dict[str, Any]) -> dict[str, Any]:
    """生成督促提醒文案。"""

    self_discipline = int(context.get("self_discipline") or 3)
    tone = "gentle" if self_discipline >= 4 else "firm" if self_discipline <= 2 else "neutral"
    due = [str(item) for item in (context.get("due_tasks") or [])]
    overdue = [str(item) for item in (context.get("overdue_tasks") or [])]
    idle_days = int(context.get("idle_days") or 0)
    days_left = context.get("days_left")

    if overdue:
        title = f"有 {len(overdue)} 个任务已逾期，今天先清 2 个"
        content = f"逾期任务：{'；'.join(overdue[:3])}。先处理优先级最高的两项，其余顺延。"
    elif due:
        title = f"今天还有 {len(due)} 个任务待完成"
        content = f"今日任务：{'；'.join(due[:3])}。按顺序完成，每完成一个就打卡。"
    elif idle_days >= 3:
        title = f"已连续 {idle_days} 天没有打卡"
        content = "今天的任务量已下调，先完成一个 30 分钟的小任务找回手感。"
    else:
        title = "今天的任务已经完成，保持节奏"
        content = "利用剩余时间做一组错题回炉，或者提前预习明天的内容。"

    actions = []
    if due:
        actions.append(f"先完成：{due[0]}")
    if overdue:
        actions.append(f"清掉逾期任务：{overdue[0]}")
    if not actions:
        actions.append("花 20 分钟回看昨天的错题")

    return {
        "title": title,
        "content": content,
        "tone": tone,
        "actions": actions[:3],
        "streak_hint": (
            f"距考试还有 {days_left} 天，保持每天打卡" if days_left else "保持每天打卡的节奏"
        ),
    }


def build_weekly_digest(context: dict[str, Any]) -> dict[str, Any]:
    """生成周报复盘文案。"""

    completion = float(context.get("completion_rate") or 0)
    done = int(context.get("done_tasks") or 0)
    total = int(context.get("total_tasks") or 0)
    recent_minutes = int(context.get("recent_minutes") or 0)

    highlights = [
        f"本周完成 {done} / {total} 个任务，完成率 {completion:.0%}",
        f"累计学习时长 {recent_minutes} 分钟",
    ]
    problems: list[str] = []
    if completion < 0.6:
        problems.append("本周完成率不足 60%，计划粒度可能偏大")
    if recent_minutes < 300:
        problems.append("本周累计学习时长偏少，需要固定每日起始时间")
    if not problems:
        problems.append("本周执行稳定，可以适度提高训练难度")

    return {
        "title": "本周学习周报",
        "highlights": highlights,
        "problems": problems,
        "next_week_plan": [
            "把薄弱科目的深度练习固定在同一时段",
            "安排一次整卷训练并记录得分率",
            "逾期任务清零，避免滚雪球",
        ],
        "closing": "用完成的任务数而不是学习时长衡量进步，下周继续保持。",
    }


OFFLINE_BUILDERS: dict[str, PayloadBuilder] = {
    "intent_routing": build_intent,
    "plan_draft": build_plan_draft,
    "task_breakdown": build_task_breakdown,
    "tutoring": build_tutoring,
    "diagnosis": build_diagnosis,
    "resource_plan": build_resource_plan,
    "nudge": build_nudge,
    "weekly_digest": build_weekly_digest,
}


def supports(task: str) -> bool:
    """是否支持该任务的离线生成。"""

    return task in OFFLINE_BUILDERS


def build_offline_payload(task: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """生成离线结构化内容。"""

    try:
        builder = OFFLINE_BUILDERS[task]
    except KeyError as exc:
        raise KeyError(f"离线模式未实现任务 {task} 的内容生成") from exc
    return builder(context or {})
