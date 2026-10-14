"""子智能体工具注册表。

聊天 Agent 不直接认识任何子智能体，它只看到「工具」：
工具名、说明与参数 schema 是模型唯一的可见面，真正的分发由这里的映射决定。
新增子智能体时只需要在这里登记一条，提示词、调度与落库会自动跟随。
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SubagentTool:
    """一个可被聊天 Agent 调起的子智能体。"""

    name: str
    """工具名，模型可见。"""

    agent: str
    """子智能体标识，与 ``AGENT_HANDLERS`` 的键一致。"""

    label: str
    """面向用户的中文名。"""

    description: str
    """给模型看的能力说明，决定模型何时选它。"""

    instruction_hint: str
    """instruction 参数的填写提示。"""

    def to_schema(self) -> dict[str, Any]:
        """转成 OpenAI 兼容的工具描述。"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": self.instruction_hint,
                        }
                    },
                    "required": ["instruction"],
                    "additionalProperties": False,
                },
            },
        }


TOOLS: tuple[SubagentTool, ...] = (
    SubagentTool(
        name="generate_plan",
        agent="planner",
        label="备考规划师",
        description=(
            "制定或整体重排学习计划。需要从零规划、备考周期变化、目标大改时使用。"
            "已有计划只需局部改动时改用 revise_plan。"
        ),
        instruction_hint="要规划的目标与侧重，例如「数学基础薄弱，前两个月重点补基础」",
    ),
    SubagentTool(
        name="breakdown_tasks",
        agent="breakdown",
        label="任务拆解师",
        description="把某个阶段或科目拆解为可打卡的每日任务清单，用于颗粒度太粗、不知从哪下手的情况。",
        instruction_hint="要拆解的范围，例如「把数学基础阶段拆成两周的任务」",
    ),
    SubagentTool(
        name="explain_concept",
        agent="tutor",
        label="答疑讲师",
        description="讲解知识点、解题步骤与易错点，会自动检索知识库。用户问「为什么」「怎么做」时使用。",
        instruction_hint="要讲解的题目或知识点原文",
    ),
    SubagentTool(
        name="review_progress",
        agent="reviewer",
        label="复盘诊断师",
        description="复盘当前进度、诊断节奏风险并给出本周调整动作。用户问进度如何、要不要调整时使用。",
        instruction_hint="希望重点诊断的方面，例如「数学是不是拖后腿了」",
    ),
    SubagentTool(
        name="recommend_resources",
        agent="resource",
        label="资料规划师",
        description="按科目与阶段推荐资料组合与真题刷法。用户问用什么资料、真题怎么刷时使用。",
        instruction_hint="要推荐资料的科目与阶段",
    ),
    SubagentTool(
        name="send_nudge",
        agent="coach",
        label="督学教练",
        description="生成督促提醒话术。用户拖延、断签或明确要求督促时使用。",
        instruction_hint="督促的具体方向，例如「最近三天没学习，帮我收心」",
    ),
    SubagentTool(
        name="revise_plan",
        agent="plan_editor",
        label="计划修订师",
        description=(
            "修改已存在的计划表：增删任务、调整任务日期与时长、整体平移进度、改计划标题或目标。"
            "已有计划需要局部改动时用它。"
        ),
        instruction_hint="要改什么，例如「数学任务往后挪三天，并给英语加一个每日背单词任务」",
    ),
    SubagentTool(
        name="advise_schools",
        agent="school_advisor",
        label="择校参谋",
        description=(
            "结合个人情况与目标，列出多所可行的候选院校，说明各自适合谁、优势与代价。"
            "用户问择校、院校对比、专业方向、报录比时使用。"
            "只提供选项与分析，不做推荐、不替用户拍板。"
        ),
        instruction_hint="择校诉求，例如「本科双非，想考计算机，希望一次上岸」",
    ),
)

TOOLS_BY_NAME: dict[str, SubagentTool] = {tool.name: tool for tool in TOOLS}
TOOLS_BY_AGENT: dict[str, SubagentTool] = {tool.agent: tool for tool in TOOLS}


def tool_schemas() -> list[dict[str, Any]]:
    """返回全部工具的 OpenAI 兼容描述。"""

    return [tool.to_schema() for tool in TOOLS]


def tool_names() -> tuple[str, ...]:
    """返回全部工具名。"""

    return tuple(tool.name for tool in TOOLS)


def describe_tools() -> list[dict[str, str]]:
    """返回工具清单，用于接口自省与文档。"""

    return [
        {"name": tool.name, "agent": tool.agent, "label": tool.label, "using": tool.description}
        for tool in TOOLS
    ]
