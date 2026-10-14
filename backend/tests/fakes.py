# 知识点：假模型的替身位置 —— 假件替换在 I/O 边界（模型工厂与向量化网络调用），
#   而不是在业务层加分支，因此真实的编排、解析与落库路径全部保留
#   （第2章 LangChain核心组件·模型）
"""测试专用假件：假模型、假向量化与内存检查点。

生产代码中已不再有任何离线降级路径：模型调用失败即失败。
测试则通过 ``install_fake_model`` 把模型工厂替换成本文件的 ``FakeChatModel``，
从而在无密钥、无网络的 CI 环境中真实地跑完工具调用、结构化解析与落库全流程。

``FakeChatModel`` 承担两个角色：

- **聊天 Agent 的调度**：解析用户输入中的关键词，产出带 ``tool_calls`` 的
  ``AIMessage``，等价地驱动``bind_tools`` 那一套原生工具调用协议；
- **子智能体的结构化产出**：从提示词中还原上下文，生成 schema 合法的 JSON 文本。

从提示词里还原上下文（而不是由生产代码传入 ``stub_context``）是刻意的：
真实模型也只能看到提示词，假模型读同一份输入才谈得上等价。
"""

import json
import re
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.agents.tools import TOOLS_BY_NAME
from app.knowledge.embeddings import BaseEmbedder
from app.knowledge.text import normalize_vector, token_hash, tokenize
from app.schemas import LearnerSnapshot, PlanDraft

PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]]

DEFAULT_SUBJECTS = ("政治", "英语", "数学", "专业课")

# 计划修订关键词。这类词要优先于「计划」判定，
# 否则「把任务往后挪三天」会被当成重新制定计划。
SHIFT_KEYWORDS = ("推迟", "延后", "顺延", "往后挪", "往后推", "挪后", "延一延")
ADD_KEYWORDS = ("增加", "添加", "加一个", "加个", "补充", "再来一个", "新增")
REMOVE_KEYWORDS = ("删除", "去掉", "取消", "移除", "不做了")
META_KEYWORDS = ("改标题", "改目标", "改策略", "计划名")

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "revise": (
        "修改计划",
        "调整计划",
        "改计划",
        "调整安排",
        *SHIFT_KEYWORDS,
        *ADD_KEYWORDS,
        *REMOVE_KEYWORDS,
    ),
    "plan": ("计划", "规划", "安排", "时间表", "怎么复习", "如何复习", "备考", "冲刺", "从哪开始"),
    "breakdown": ("拆解", "拆分", "细化", "每天做什么", "每日任务", "任务分配"),
    "tutor": ("为什么", "怎么理解", "讲解", "不懂", "不会", "这道题", "公式", "原理", "推导"),
    "review": ("复盘", "总结", "诊断", "进度", "落后", "焦虑", "来得及", "效率", "完成度", "状态"),
    "resource": ("资料", "书单", "教材", "真题", "题库", "用什么书", "网课", "讲义"),
    "nudge": ("提醒", "督促", "坚持不下去", "打卡", "断签", "没动力"),
    # 择校词表刻意避开「备考」「规划」「计划」：那几个词属于 plan，
    # 一旦共用，「帮我规划择校」就会被判成生成计划。
    "school": (
        "择校",
        "选学校",
        "选院校",
        "院校",
        "报录比",
        "性价比",
        "哪个学校",
        "目标院校",
        "招生简章",
        "招生目录",
        "专业目录",
    ),
}

INTENT_AGENTS: dict[str, list[str]] = {
    "revise": ["plan_editor"],
    "plan": ["planner", "breakdown"],
    "breakdown": ["breakdown"],
    "tutor": ["tutor"],
    "review": ["reviewer"],
    "resource": ["resource"],
    "nudge": ["coach"],
    "school": ["school_advisor"],
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


# --------------------------------------------------------------------------
# 从提示词还原上下文
# --------------------------------------------------------------------------

SECTION_RE = re.compile(r"^【(?P<name>[^】]+)】$", re.MULTILINE)


def message_text(message: BaseMessage) -> str:
    """把消息内容压平成纯文本。"""

    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item if isinstance(item, str) else str(item.get("text", ""))
            for item in content
            if isinstance(item, (str, dict))
        )
    return str(content)


def _section(text: str, *headings: str) -> str:
    """取出指定标题下的正文，直到下一个标题为止。"""

    marks = list(SECTION_RE.finditer(text))
    for index, mark in enumerate(marks):
        if mark.group("name") not in headings:
            continue
        start = mark.end()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        return text[start:end].strip()
    return ""


def _search(pattern: str, text: str, cast: Callable[[str], Any]) -> Any:
    matched = re.search(pattern, text)
    return cast(matched.group(1)) if matched else None


BULLET_RE = re.compile(r"^\s*(?:[-·*]|\d+\.)\s*")
NO_DATA = "（暂无数据）"


def _strip_bullet(line: str) -> str:
    """去掉列表标记与薄弱标记，还原出纯名目。"""

    return BULLET_RE.sub("", line).strip().removesuffix("【薄弱】")


def _bullets_of(text: str, label: str) -> list[str]:
    """取出「标签（N 项）：」后面紧跟的那组列表项。"""

    matched = re.search(rf"{label}（\d+ 项）：(.*?)(?=\n(?!\s*-)|\Z)", text, re.DOTALL)
    if not matched:
        return []
    items = [_strip_bullet(line) for line in matched.group(1).splitlines() if line.strip()]
    return [item for item in items if item and item != NO_DATA]


def parse_prompt_context(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    """从提示词中还原离线生成所需的上下文。

    真实模型读到的就是这些文字，因此假模型读同一份输入是等价的，
    而不是绕过提示词直接拿到业务对象。
    """

    text = "\n".join(message_text(item) for item in messages)

    subjects = [
        _strip_bullet(item)
        for item in re.findall(r"^(.+?)｜类别 ", text, re.MULTILINE)
    ]
    weak = [
        _strip_bullet(item)
        for item in re.findall(r"^(.+?)【薄弱】｜类别 ", text, re.MULTILINE)
    ]

    request = _section(
        text,
        "本次诉求",
        "用户输入",
        "考生提出的问题",
        "复盘诉求",
        "资料需求",
        "待拆解的阶段或目标",
        "用户诉求",
        "考生诉求",
    )
    plan_tasks = [
        str(item).strip()
        for item in re.findall(r"^\s+· \[\w+\] \S+ (?:\S+｜)?(.+?)（", text, re.MULTILINE)
    ]
    durations = [
        int(item) for item in re.findall(r"单任务时长 \d+-(\d+) 分钟", text)
    ]

    return {
        "request": request,
        "scope": request,
        "subjects": subjects,
        "weak_subjects": weak,
        "days_left": _search(r"剩余天数：(\d+) 天", text, int),
        "daily_hours": _search(r"每日可投入：([\d.]+) 小时", text, float),
        "attention_span": _search(r"单次专注时长：(\d+) 分钟", text, int),
        "self_discipline": _search(r"自律程度：(\d+)/5", text, int),
        "completion_rate": _search(r"整体完成率 ([\d.]+)%", text, lambda value: float(value) / 100),
        "total_tasks": _search(r"任务总数 (\d+)，已完成", text, int),
        "done_tasks": _search(r"已完成为? (\d+)，进行中", text, int) or 0,
        "overdue_count": _search(r"逾期 (\d+)", text, int) or 0,
        "idle_days": _search(r"连续未学习 (\d+) 天", text, int) or 0,
        "recent_minutes": _search(r"近 7 天学习时长 (\d+) 分钟", text, int) or 0,
        "plan_tasks": plan_tasks,
        "due_tasks": _bullets_of(text, "今日待完成任务"),
        "overdue_tasks": _bullets_of(text, "已逾期任务"),
        # 择校与简报：核验入口必须由系统注入，假模型只照抄提示词里给的那份
        "official_links": _section(text, "官方核验入口"),
        "tracked_context": _section(text, "正在跟踪的院校"),
        # 计划评审所需的草稿指标
        "horizon_days": _search(r"计划周期：(\d+) 天", text, int),
        "stage_count": _search(r"阶段数量：(\d+)｜", text, int),
        "task_count": _search(r"任务总数：(\d+)", text, int),
        "max_task_minutes": durations[0] if durations else None,
    }


# --------------------------------------------------------------------------
# 结构化内容生成
# --------------------------------------------------------------------------


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


def build_plan_review(context: dict[str, Any]) -> dict[str, Any]:
    """对学习计划做规则化评审。

    评审不是走过场：这里真的会校验任务粒度、阶段划分、科目覆盖与输入完整性，
    因此假模型也能给出有依据的评审结论。
    """

    issues: list[dict[str, Any]] = []
    attention = int(context.get("attention_span") or 50)
    max_minutes = int(context.get("max_task_minutes") or 0)
    stage_count = int(context.get("stage_count") or 0)
    task_count = int(context.get("task_count") or 0)
    horizon = int(context.get("horizon_days") or 0)
    days_left = context.get("days_left")
    subjects = _subjects(context)
    weak = _weak_subjects(context)

    if max_minutes > attention:
        issues.append(
            {
                "severity": "high",
                "category": "任务粒度",
                "detail": f"存在 {max_minutes} 分钟的单个任务，超过单次专注时长 {attention} 分钟",
                "suggestion": "把超长任务拆成两个专注时长以内的小任务",
            }
        )

    if horizon >= 90 and stage_count < 3:
        issues.append(
            {
                "severity": "high",
                "category": "阶段划分",
                "detail": f"计划周期 {horizon} 天但只有 {stage_count} 个阶段，缺少阶段性检验点",
                "suggestion": "至少划分基础、强化、冲刺三个阶段并各自设定验收标准",
            }
        )

    if task_count < len(subjects) * 2:
        issues.append(
            {
                "severity": "medium",
                "category": "任务覆盖",
                "detail": f"{len(subjects)} 门科目仅拆出 {task_count} 个任务，单科训练量不足",
                "suggestion": "每门科目在每个阶段至少安排一个学习任务与一个练习任务",
            }
        )

    missing_weak = [name for name in sorted(weak) if name not in subjects]
    if missing_weak:
        issues.append(
            {
                "severity": "medium",
                "category": "科目覆盖",
                "detail": f"薄弱科目 {'、'.join(missing_weak)} 未出现在计划科目中",
                "suggestion": "把薄弱科目补进计划并提升其任务优先级",
            }
        )

    if days_left is None:
        issues.append(
            {
                "severity": "low",
                "category": "输入完整性",
                "detail": "档案缺少考试日期，计划按默认周期排布，可能与真实节奏不匹配",
                "suggestion": "补充考试日期后重新生成计划",
            }
        )

    weights = {"high": 15, "medium": 8, "low": 3}
    penalty = sum(weights.get(str(item["severity"]), 0) for item in issues)
    score = max(40, 100 - penalty)
    blocking = any(item["severity"] == "high" for item in issues)

    return {
        "approved": not blocking,
        "score": score,
        "summary": (
            f"计划整体可用，评分 {score} 分，发现 {len(issues)} 个待改进项"
            if issues
            else f"计划结构完整，评分 {score} 分，可以直接执行"
        ),
        "issues": issues,
        "improvements": [
            "把单次任务控制在专注时长以内，超长任务一律拆分",
            "每门科目在每个阶段都安排学习与练习两类任务",
            "每个阶段结束设置复盘节点，用得分率检验阶段成果",
        ],
    }


DAY_PATTERN = re.compile(r"(\d+)\s*天")


def _mentioned_subject(request: str, subjects: list[str]) -> str:
    """返回请求中点名的科目，未点名时退回第一个科目。"""

    for name in subjects:
        if name and name in request:
            return name
    return subjects[0] if subjects else ""


def _first_pending_task(context: dict[str, Any]) -> str:
    """返回一个可被引用的待办任务标题。"""

    for key in ("overdue_tasks", "due_tasks", "plan_tasks"):
        items = context.get(key) or []
        for item in items:
            text = str(item).strip()
            if text:
                return text
    return ""


def build_plan_revision(context: dict[str, Any]) -> dict[str, Any]:
    """把修订诉求翻译成计划修订指令。

    假模型无法理解自由表述，因此只在能明确识别意图时才产出操作；
    识别不了就返回空操作，由总结环节如实说明，而不是臆造改动。
    """

    request = str(context.get("request", ""))
    subjects = _subjects(context)

    # 没有现存计划时不做任何修订，避免凭空造出改动
    if not context.get("plan_tasks"):
        return {
            "summary": "当前还没有学习计划，无法执行修订，请先生成计划",
            "ops": [],
        }

    if any(word in request for word in SHIFT_KEYWORDS):
        matched = DAY_PATTERN.search(request)
        days = int(matched.group(1)) if matched else 3
        return {
            "summary": f"把未完成任务的日期整体后移 {days} 天",
            "ops": [{"action": "shift_tasks", "shift_days": days}],
        }

    if any(word in request for word in REMOVE_KEYWORDS):
        target = _first_pending_task(context)
        if target:
            return {
                "summary": f"删除任务「{target}」",
                "ops": [{"action": "remove_task", "task_title": target}],
            }
        return {"summary": "没有找到可以删除的待办任务", "ops": []}

    if any(word in request for word in ADD_KEYWORDS):
        subject = _mentioned_subject(request, subjects)
        return {
            "summary": f"为「{subject}」补充一个每日任务",
            "ops": [
                {
                    "action": "add_task",
                    "title": f"{subject}每日巩固练习并整理错题",
                    "description": "完成 20 道对应章节练习，整理错题并标注卡住的那一步",
                    "subject": subject,
                    "day_offset": 0,
                    "duration_minutes": 60,
                    "priority": "high" if subject in _weak_subjects(context) else "medium",
                }
            ],
        }

    if any(word in request for word in META_KEYWORDS):
        return {
            "summary": "更新计划的目标与策略描述",
            "ops": [
                {
                    "action": "update_meta",
                    "plan_goal": f"围绕{'、'.join(subjects)}完成一轮系统复习并稳定得分",
                    "plan_strategy": "按阶段推进，每阶段结束用真题得分率检验成果。",
                }
            ],
        }

    return {
        "summary": "无法解析这条修改要求，未对计划做任何改动",
        "ops": [],
    }


FAKE_SCHOOL_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "name": "某某大学",
        "major": "计算机科学与技术",
        "fit_for": "本科基础扎实、能承受高强度竞争的考生",
        "pros": ["学科积累深，专业课资料容易找到", "所在地实习与就业资源集中"],
        "cons": ["报考人数多，复试竞争激烈", "专业课统考科目复习量大"],
        "evidence": ["检索片段提到该校近年招生规模，具体数字需以官方目录为准"],
    },
    {
        "name": "某某理工大学",
        "major": "计算机技术",
        "fit_for": "希望稳妥落地、更看重一次上岸的考生",
        "pros": ["专业课自命题，复习范围相对明确", "招生规模较大，录取名额相对宽裕"],
        "cons": ["院校层次低于第一档，就业招牌弱一些", "热门方向导师资源紧张"],
        "evidence": ["检索片段提到该校自命题科目，科目代码需以官方目录为准"],
    },
    {
        "name": "某某师范大学",
        "major": "教育技术学",
        "fit_for": "愿意转向教育信息化方向、跨考压力较小的考生",
        "pros": ["跨考友好，专业课以记忆与理解为主", "师范类就业方向相对稳定"],
        "cons": ["与本科专业跨度大，需要重建知识体系", "对口技术岗位口径较窄"],
        "evidence": ["检索片段提到该校该专业接收跨考生，具体要求需以招生简章为准"],
    },
)
"""假模型的候选院校池：名称与 fit_for 互不相同，符合 Schema 的机械不变式。

刻意使用「某某」式占位名与不含具体分数线的措辞：假件也不该产出
看起来权威的数字，否则测试会默认「编造分数是可以接受的」。
"""


def build_school_advice(context: dict[str, Any]) -> dict[str, Any]:
    """生成候选院校对比，刻意不给出任何排序或推荐。"""

    return {
        "candidates": [dict(item) for item in FAKE_SCHOOL_CANDIDATES],
        "comparison_dimensions": [
            "近三年复试线与报录比（以官方公布为准）",
            "专业课科目与参考书是否与你的复习基础匹配",
            "地域与未来就业方向",
            "复试差额比例与调剂空间",
        ],
        "decision_questions": [
            "你更在意一次上岸，还是更在意院校层次？",
            "能否接受异地读研与三年后的就业半径变化？",
            "专业课从零开始，你愿意投入多长时间？",
        ],
        # 核验入口由系统注入，假模型照规矩留空，与真提示词的要求一致
        "verification_links": [],
        "caveats": [
            "以上为候选与代价的客观梳理，是否报考由你自己决定。",
            "院校信息变化快，务必以院校研究生院官网与研招网的官方招生简章为准。",
        ],
    }


def build_school_brief(context: dict[str, Any]) -> dict[str, Any]:
    """生成每日院校简报。

    只跟踪院校的**名称**：提示词里没有具体分数线，假模型也就不该凭空写出来——
    真提示词同样被要求不得复述片段里的数字。
    """

    tracked = [
        line.strip().lstrip("-·* ").strip()
        for line in str(context.get("tracked_context") or "").splitlines()
        if line.strip()
    ]
    names = [item.split("｜")[0].strip() for item in tracked] or ["目标院校"]

    return {
        "title": "今日院校简报",
        "summary": f"今天为你整理了 {len(names)} 所跟踪院校的动向，供你自行判断。",
        "highlights": [f"{name}：建议自行核对最新招生简章与专业目录" for name in names],
        # 核验入口由系统按确定性规则注入，这里照规矩留空
        "links": [],
        "caveats": ["院校信息变化快，最终以院校研究生院官网与研招网的官方公告为准。"],
    }


# 知识点：假模型的等价性 —— 替身要与真实模型消费同一份输入（提示词）并产出同形状的输出，
#   否则测试验证的是假件的想象而不是真实链路（第2章 LangChain核心组件·模型）
# --------------------------------------------------------------------------
# 正文生成（双轨信封的 narrative 一轨）
#
# 真实模型在同一次调用里既写正文、又填结构化字段；假模型必须做同样的事，
# 否则「子智能体正文原样回灌给聊天 Agent」这条链路在测试中根本不会被走到。
# --------------------------------------------------------------------------

NarrativeBuilder = Callable[[dict[str, Any]], str]


def _block(title: str, lines: Sequence[Any]) -> str:
    """渲染一个 markdown 小节，空内容直接消失。"""

    body = "\n".join(f"- {line}" for line in lines if str(line).strip())
    return f"**{title}**\n{body}" if body else ""


def _doc(*blocks: str) -> str:
    return "\n\n".join(block for block in blocks if block.strip())


def narrate_plan_draft(payload: dict[str, Any]) -> str:
    """分阶段学习计划的正文。"""

    stages = payload.get("stages") or []
    return _doc(
        f"## {payload.get('title') or '分阶段备考计划'}",
        f"目标：{payload.get('goal') or '按阶段推进备考'}",
        f"总周期 {payload.get('horizon_days')} 天，每日投入 {payload.get('daily_hours')} 小时，"
        f"共 {payload.get('total_tasks')} 个任务。",
        _block(
            "阶段安排",
            [
                f"第 {stage.get('start_offset')}-{stage.get('end_offset')} 天｜"
                f"{stage.get('name')}：{stage.get('focus')}"
                for stage in stages
            ],
        ),
        str(payload.get("strategy") or ""),
        _block("注意事项", payload.get("notes") or []),
        "需要把某个阶段继续拆成每日任务，直接告诉我阶段名称即可。",
    )


def narrate_task_breakdown(payload: dict[str, Any]) -> str:
    """任务拆解清单的正文。"""

    tasks = payload.get("tasks") or []
    return _doc(
        f"## 任务拆解：{payload.get('scope') or '当前阶段'}",
        str(payload.get("summary") or ""),
        _block(
            "任务清单",
            [
                f"第 {task.get('day_offset')} 天｜{task.get('subject') or '通用'}｜"
                f"{task.get('title')}（{task.get('duration_minutes')} 分钟，"
                f"优先级 {task.get('priority')}）"
                for task in tasks[:10]
            ],
        ),
        _block("排期建议", payload.get("notes") or []),
    )


def narrate_tutoring(payload: dict[str, Any]) -> str:
    """知识点讲解的正文：解题步骤与易错点必须原文出现。

    这是阶段 1 的验收重点——旧实现里这两段会被摘要压掉，用户看不到。
    """

    steps = payload.get("steps") or []
    pitfalls = payload.get("pitfalls") or []
    return _doc(
        f"## {payload.get('subject') or '知识点'}讲解",
        str(payload.get("question_summary") or ""),
        _block("解题步骤", [f"{index}. {step}" for index, step in enumerate(steps, start=1)]),
        _block("易错点", [f"{index}. {item}" for index, item in enumerate(pitfalls, start=1)]),
        _block("关键结论", payload.get("key_points") or []),
        _block("自查问题", payload.get("followups") or []),
        _block("配套练习", payload.get("related_practice") or []),
    )


def narrate_diagnosis(payload: dict[str, Any]) -> str:
    """备考复盘诊断的正文。"""

    risks = payload.get("risks") or []
    return _doc(
        "## 备考复盘诊断",
        str(payload.get("summary") or ""),
        _block("关键发现", payload.get("findings") or []),
        _block(
            "风险与对策",
            [
                f"[{risk.get('level')}] {risk.get('title')}：{risk.get('detail')}"
                f"→ {risk.get('suggestion')}"
                for risk in risks
            ],
        ),
        _block("调整建议", payload.get("adjustments") or []),
        str(payload.get("encouragement") or ""),
    )


def narrate_resource_plan(payload: dict[str, Any]) -> str:
    """资料组合建议的正文。"""

    items = payload.get("items") or []
    return _doc(
        "## 资料组合建议",
        str(payload.get("summary") or ""),
        _block(
            "资料清单",
            [
                f"{item.get('subject') or '通用'}｜{item.get('stage')}｜"
                f"{item.get('name')}：{item.get('usage')}"
                for item in items[:12]
            ],
        ),
        _block("使用建议", payload.get("tips") or []),
    )


def narrate_nudge(payload: dict[str, Any]) -> str:
    """督促提醒的正文。"""

    return _doc(
        f"## {payload.get('title') or '今日提醒'}",
        str(payload.get("content") or ""),
        _block("现在就做", payload.get("actions") or []),
        str(payload.get("streak_hint") or ""),
    )


def _target_of(op: dict[str, Any]) -> str:
    """取一条修订操作里最能说明「改了什么」的那个字段。"""

    for key in ("task_title", "title", "plan_title", "plan_goal"):
        if op.get(key):
            return str(op[key])
    return "计划整体"


def narrate_plan_revision(payload: dict[str, Any]) -> str:
    """计划修订提案的正文。"""

    ops = payload.get("ops") or []
    return _doc(
        "## 计划修订提案",
        str(payload.get("summary") or ""),
        _block(
            "具体改动",
            [
                f"{op.get('action')}｜{_target_of(op)}"
                f"（第 {op.get('day_offset')} 天，{op.get('shift_days')} 天）"
                for op in ops
            ],
        ),
        "确认无误后我才会真正写入计划表。",
    )


def narrate_school_advice(payload: dict[str, Any]) -> str:
    """择校候选对比的正文：逐所说明适合谁与代价，不给结论。"""

    candidates = payload.get("candidates") or []
    return _doc(
        "## 择校候选分析",
        f"共 {len(candidates)} 所候选，各有利弊，选择权在你。",
        _block(
            "候选院校",
            [
                f"{item.get('name')}（{item.get('major') or '专业待定'}）："
                f"适合{item.get('fit_for')}｜"
                f"优势：{'；'.join(item.get('pros') or [])}｜"
                f"代价：{'；'.join(item.get('cons') or [])}"
                for item in candidates
            ],
        ),
        _block("建议你自己比较的维度", payload.get("comparison_dimensions") or []),
        _block("需要你自己回答的问题", payload.get("decision_questions") or []),
        _block("注意事项", payload.get("caveats") or []),
        "以上是候选与代价的梳理，最终报考哪一所由你决定。",
    )


FAKE_BUILDERS: dict[str, PayloadBuilder] = {
    "plan_draft": build_plan_draft,
    "task_breakdown": build_task_breakdown,
    "tutoring": build_tutoring,
    "diagnosis": build_diagnosis,
    "resource_plan": build_resource_plan,
    "nudge": build_nudge,
    "weekly_digest": build_weekly_digest,
    "plan_review": build_plan_review,
    "plan_revision": build_plan_revision,
    "school_advisor": build_school_advice,
    "school_brief": build_school_brief,
}

NARRATIVE_BUILDERS: dict[str, NarrativeBuilder] = {
    "plan_draft": narrate_plan_draft,
    "task_breakdown": narrate_task_breakdown,
    "tutoring": narrate_tutoring,
    "diagnosis": narrate_diagnosis,
    "resource_plan": narrate_resource_plan,
    "nudge": narrate_nudge,
    "plan_revision": narrate_plan_revision,
    "school_advisor": narrate_school_advice,
}

NARRATIVE_TASKS = frozenset(NARRATIVE_BUILDERS)
"""会走双轨信封的任务：与 ``app.llm.tasks.SUBAGENT_TASKS`` 一一对应。"""

CHAT_AGENT_TASK = "chat_agent"

FINAL_REPLY = "已根据你的诉求调度对应能力，结论见上。接下来建议先完成最近一个待办任务。"

TOKEN_DELTA_CHARS = 12
"""假模型的 token 分块粒度：真实提供方的切分不可预测，但必须真的分多块。"""

REQUEST_LOG: list[tuple[str, list[BaseMessage]]] = []
"""假模型收到的每一次请求，按调用顺序记录。

给用例一个 spy 视角：断言「提示词里到底有什么」——例如多轮历史有没有真的
被拼进消息列表，而不是只断言最终回答看起来对。
"""


def recorded_requests(task: str | None = None) -> list[list[BaseMessage]]:
    """返回假模型收到的请求消息列表，可按任务过滤。"""

    return [messages for name, messages in REQUEST_LOG if task is None or name == task]


def pick_agents(request: str) -> list[str]:
    """按关键词挑选子智能体，等价于真实模型决定调哪些工具。"""

    lowered = request.lower()
    scores = {
        intent: sum(1 for word in words if word in lowered)
        for intent, words in INTENT_KEYWORDS.items()
    }
    best = max(scores, key=lambda key: scores[key])
    return INTENT_AGENTS[best] if scores[best] else INTENT_AGENTS["chat"]


def pick_tools(request: str) -> list[str]:
    """按关键词返回工具名，与 ``TOOLS_BY_NAME`` 的键一致。"""

    by_agent = {tool.agent: tool.name for tool in TOOLS_BY_NAME.values()}
    names: list[str] = []
    for agent in pick_agents(request):
        name = by_agent.get(agent)
        if name is not None and name not in names:
            names.append(name)
    return names


# --------------------------------------------------------------------------
# 假模型
# --------------------------------------------------------------------------


class StubEmbedder(BaseEmbedder):
    """确定性哈希向量，仅测试使用。

    采用 hashing trick：同一 token 恒映射到同一维度并带符号，
    因此两段文本重叠越多、余弦相似度越高——CI 中的检索依然有意义，
    而不是随机噪声。生产端只保留真实向量化实现，本类由 ``tests/fakes.py`` 承载。
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in tokenize(text):
            digest = token_hash(token)
            index = digest % self.dimension
            sign = 1.0 if (digest >> 63) & 1 == 0 else -1.0
            vector[index] += sign
        return normalize_vector(vector)


class FakeChatModel(BaseChatModel):
    """测试专用模型：工具调用与结构化产出都可预期。

    ``task`` 与生产代码传给 ``build_chat_model`` 的标识一致，
    因此同一个假模型可以覆盖聊天 Agent 与全部子智能体。
    """

    task: str = CHAT_AGENT_TASK

    @property
    def _llm_type(self) -> str:
        return "kaoyan-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":
        """声明支持工具绑定；真实模型据此产出 tool_calls。"""

        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._build_message(messages))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步路径直接复用同步实现，保证结果确定且不依赖线程池。"""

        return self._generate(messages, stop, None, **kwargs)

    def _build_message(self, messages: list[BaseMessage]) -> AIMessage:
        REQUEST_LOG.append((self.task, list(messages)))
        if self.task != CHAT_AGENT_TASK:
            return AIMessage(content=self._structured_reply(messages))
        return self._chat_reply(messages)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """按固定粒度逐块吐出，模拟真实提供方的增量流。

        若沿用基类「一次吐一整条」的兜底，连续 token 帧这条验收在测试里
        永远会假通过，因此这里必须真的分多块。
        """

        message = self._build_message(messages)
        text = message_text(message)

        for start in range(0, len(text), TOKEN_DELTA_CHARS):
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=text[start : start + TOKEN_DELTA_CHARS])
            )

        if not text:
            # 工具轮没有正文，但 tool_calls 必须原样到达
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=message.tool_calls)
            )

    def _structured_reply(self, messages: list[BaseMessage]) -> str:
        """子智能体任务：产出双轨信封的 JSON 文本。"""

        builder = FAKE_BUILDERS.get(self.task)
        if builder is None:  # pragma: no cover - 未登记任务说明测试写错了
            raise KeyError(f"假模型未实现任务 {self.task} 的内容生成")

        payload = builder(parse_prompt_context(messages))
        narrate = NARRATIVE_BUILDERS.get(self.task)
        if narrate is None:
            # 不走双轨信封的任务（如计划评审）：直接给业务 Schema 本身
            return json.dumps(payload, ensure_ascii=False)
        return json.dumps({"narrative": narrate(payload), "data": payload}, ensure_ascii=False)

    def _chat_reply(self, messages: list[BaseMessage]) -> AIMessage:
        """聊天 Agent：先按关键词派单，拿到工具结果后把正文整合成最终回答。

        真实模型在读到 ``ToolMessage`` 里的子智能体正文后，会把要点原样写进回答；
        假模型照做，阶段 1「正文不被摘要压掉」这条验收才在测试中有意义。
        """

        bodies = [
            message_text(item).strip()
            for item in messages
            if isinstance(item, ToolMessage) and message_text(item).strip()
        ]
        if bodies:
            return AIMessage(
                content="已根据你的诉求调度对应能力，以下是完整结论：\n\n"
                + "\n\n".join(bodies)
            )

        # 只取【用户输入】那一段做判定：整份提示词里满是「备考」「计划」这类
        # 背景词汇，拿全文匹配会让关键词路由彻底失真。
        request = parse_prompt_context(messages)["request"]
        names = pick_tools(request)
        if not names:
            return AIMessage(content=FINAL_REPLY)

        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": {"instruction": request},
                    "id": f"call_{index}",
                }
                for index, name in enumerate(names)
            ],
        )


def install_fake_model(monkeypatch: Any) -> None:
    """把模型工厂替换成假模型。

    ``build_chat_model`` 被两处按值引用，因此两处都要打补丁：
    工厂自身（供 ``invoke_agent_task`` 使用）与聊天 Agent 模块。
    """

    REQUEST_LOG.clear()

    def factory(
        task: str, provider: str | None = None, **kwargs: Any
    ) -> FakeChatModel:
        return FakeChatModel(task=task)

    import app.llm.factory as factory_module
    import app.workflows.chat_agent as chat_agent_module

    monkeypatch.setattr(factory_module, "build_chat_model", factory)
    monkeypatch.setattr(chat_agent_module, "build_chat_model", factory)


# 知识点：Checkpointer —— 内存检查点与 SQLite/PostgreSQL 实现在「按 thread_id 存取状态」
#   这一点上等价，替换掉它就能在用例之间彻底隔离中断状态（第5章 LangGraph·人工确认）
def install_fake_checkpointer(monkeypatch: Any) -> None:
    """把工作流检查点替换成内存实现。

    每个用例一份新实例：会话 ID 会从 1 重新开始，用真实文件型检查点的话，
    上一个用例遗留的中断会被下一个用例的恢复请求读到。
    """

    from langgraph.checkpoint.memory import InMemorySaver

    import app.workflows.checkpoint as checkpoint_module

    monkeypatch.setattr(checkpoint_module, "_saver", InMemorySaver(), raising=False)


def install_fake_embedder(monkeypatch: Any) -> None:
    """只替换向量化最外层的网络调用，返回确定性哈希向量。

    刻意不去替换 ``build_embedder`` 工厂：配置校验、提供方选择、批量切分
    这些真实逻辑全部保留，因此「配置不全时应报错」这类契约在测试中依然成立。
    """

    import app.knowledge.embeddings as embeddings_module

    async def fake_embed(self: Any, texts: list[str]) -> list[list[float]]:
        return await StubEmbedder(self.dimension).embed(texts)

    monkeypatch.setattr(embeddings_module.OpenAICompatEmbedder, "embed", fake_embed)


FAKE_SEARCH_RESULTS: tuple[dict[str, str], ...] = (
    {
        "title": "某校 2026 年硕士研究生招生简章",
        "url": "https://example.edu.cn/zs/2026",
        "snippet": "该校招收计算机科学与技术专业硕士，初试科目含 408 计算机学科专业基础综合。",
    },
    {
        "title": "某校 计算机技术 复试分数线公告",
        "url": "https://example.edu.cn/zs/2026/line",
        "snippet": "分数线以当年官方公告为准，往年数据仅供参考。",
    },
    {
        "title": "研招网 · 硕士专业目录查询",
        "url": "https://yz.chsi.com.cn/zsml/",
        "snippet": "招生人数与考试科目以当年专业目录为准。",
    },
)


def install_fake_search(monkeypatch: Any) -> None:
    """只替换搜索最外层的网络调用，返回确定性结果。

    与 ``install_fake_embedder`` 同理：刻意不替换 ``build_search_client`` 工厂，
    配置校验与提供方选择这些真实逻辑保留，因此「无密钥应报配置错误」的契约依然成立。
    """

    import app.search.client as search_module
    from app.search.types import SearchResult

    async def fake_search(self: Any, query: str, *, top_k: int) -> list[SearchResult]:
        return [
            SearchResult(
                title=item["title"],
                url=item["url"],
                snippet=item["snippet"],
                score=1.0 - index * 0.1,
                provider=self.provider,
            )
            for index, item in enumerate(FAKE_SEARCH_RESULTS[:top_k])
        ]

    monkeypatch.setattr(search_module.TavilySearchClient, "search", fake_search)
    monkeypatch.setattr(search_module.BochaSearchClient, "search", fake_search)


# --------------------------------------------------------------------------
# 领域夹具
# --------------------------------------------------------------------------


def review_context(learner: LearnerSnapshot, draft: PlanDraft) -> dict[str, Any]:
    """构造计划评审所需的上下文。"""

    durations = [task.duration_minutes for stage in draft.stages for task in stage.tasks] or [0]
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