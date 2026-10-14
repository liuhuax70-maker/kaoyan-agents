"""择校参谋的结构化输出。

「不替用户做决定」这条产品硬约束在这里靠**结构**强制，而不是靠提示词请求模型自觉：

1. ``extra="forbid"`` 让排序、推荐、结论这类字段**根本不存在**。Pydantic 只在
   ``extra="forbid"`` 时才把 ``additionalProperties: false`` 写进
   ``model_json_schema()``，而提示词渲染只剥掉字符串型的 ``title`` 注解
   （见 ``app/prompts/context.py::render_output_contract``）——所以这条禁则在模型
   看到的契约文本里是**可见的**，不只是散文。模型一旦吐 ``{"recommended": ...}``
   或 ``"rank": 1``，就是校验失败并被回灌重试。
2. ``min_length`` 把「只给一所学校」「缺优劣势」这类退化输出挡在解析期。
3. ``@model_validator`` 只查两条机械不变式：候选不重名、``fit_for`` 不重复。
   这是「多个候选」塌缩成「同一个答案换个说法」的唯一两种机械形式。
   刻意**不查**任何「是不是有一所悄悄最优」的启发式——那类规则会在合法输出上误报，
   白白烧掉重试预算，最后变成 StructuredOutputError。
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 知识点：结构化输出的封闭契约 —— 声明 additionalProperties: false 后，「不许出现的字段」
#   由 JSON Schema 而非提示词禁令来保证，模型多吐一个键就是可拦截的校验错误
#   （第2章 LangChain核心组件·结构化输出）
_FORBID_EXTRA = ConfigDict(extra="forbid")


class SchoolCandidate(BaseModel):
    """一所候选院校，以及它的适用人群与代价。

    字段里**没有** 排名、得分、推荐度、优先级：能不能报由用户自己判断，
    产品只负责把「选了它意味着什么」摆清楚。
    """

    model_config = _FORBID_EXTRA

    name: str = Field(min_length=2, max_length=128, description="院校名称，如 某某大学")
    major: str = Field(default="", max_length=128, description="拟报考专业/方向")
    fit_for: str = Field(
        min_length=4,
        max_length=200,
        description="这所院校与专业的组合适合什么样的考生，一句话说清画像",
    )
    pros: list[str] = Field(
        min_length=1,
        max_length=6,
        description="优势，每条一个具体理由，不得空泛恭维",
    )
    cons: list[str] = Field(
        min_length=1,
        max_length=6,
        description="劣势与代价，必须真实存在；没有劣势的院校不存在，不许留空",
    )
    evidence: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="上述判断所依据的线索；来自联网片段时须注明来源不确定",
    )


class SchoolAdvisorAnswer(BaseModel):
    """一次择校咨询的完整答复。"""

    model_config = _FORBID_EXTRA

    candidates: list[SchoolCandidate] = Field(
        min_length=3,
        max_length=6,
        description="至少三所候选院校，覆盖不同难度档位，供用户权衡",
    )
    comparison_dimensions: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="建议用户自己拿来比较的维度，如 报录比、专业课难度、地域",
    )
    decision_questions: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="需要用户自己回答的问题；答案决定权完全在用户",
    )
    verification_links: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="留空即可：核验入口由系统按确定性规则注入，模型不得自行编造院校网址",
    )
    caveats: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="本答复的局限，如信息可能过期、需以官方招生简章为准",
    )

    @model_validator(mode="after")
    def _candidates_must_be_distinct(self) -> Self:
        """候选取自同一所院校、或描述彼此雷同，等于只给了一个答案。

        跨字段规则不会出现在 JSON Schema 里（模型看不到），因此
        ``SCHOOL_ADVISOR_ROLE.extra_rules`` 里必须再复述一遍。
        """

        names = [item.name.strip() for item in self.candidates]
        if len(set(names)) != len(names):
            raise ValueError("候选院校不得重复：重复名称会把「多所候选」退化成单一答案")

        profiles = [item.fit_for.strip() for item in self.candidates]
        if len(set(profiles)) != len(profiles):
            raise ValueError("候选院校的适用人群描述不得雷同：雷同等同于只给出一所")

        return self


class TrackedSchoolSnapshot(BaseModel):
    """watch-list 里的一所院校，供提示词渲染使用。

    有这一层是因为 ``app/agents/*`` 只依赖快照而不依赖 ORM（见
    ``app/services/snapshots.py`` 的模块文档）：简报的提示词组装因此可以
    脱离数据库单测，``TrackedSchool`` 改列也不会渗透进智能体逻辑。
    """

    name: str
    major: str = ""
    status: str = "candidate"
    fit_for: str = ""
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class SchoolBrief(BaseModel):
    """每日院校简报的结构化内容。"""

    model_config = _FORBID_EXTRA

    title: str = Field(default="今日院校简报", max_length=80)
    summary: str = Field(
        default="",
        max_length=400,
        description="今天这几所院校有什么值得注意的动向，两三句话说清",
    )
    highlights: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="逐条要点，每条注明对应院校",
    )
    links: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="留空即可：核验入口由系统按确定性规则注入",
    )
    caveats: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="信息可能滞后，最终以院校官方招生简章为准",
    )