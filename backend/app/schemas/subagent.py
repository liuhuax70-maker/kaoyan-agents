# 知识点：结构化输出的双轨信封 —— 同一次调用既要产出驱动落库的结构化数据，
#   又要产出面向用户的完整正文；两者装进同一个信封，模型只需调用一次，
#   因此不再需要「先结构化、再二次总结」那道会把内容压掉的工序
#   （第2章 LangChain核心组件·结构化输出）
"""子智能体输出的双轨信封。

子智能体的产出有两种用途，缺一不可：

- ``narrative``：面向用户的完整 markdown 正文，原样回灌给聊天 Agent 作为工具结果；
- ``data``：结构化产物，驱动落库、渲染与后续统计。

把两者放进同一次调用的同一个信封，是「回答质量」这条线的关键：
此前的做法是先让模型产出结构化字段，再由确定性代码截取前几条渲染成摘要，
答疑讲师给出的解题步骤与易错点到了用户手上往往只剩标题。
"""

from functools import cache
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class SubagentReply(BaseModel, Generic[SchemaT]):
    """子智能体的一次产出：正文与结构化数据各一份。"""

    narrative: str = Field(
        description=(
            "面向用户的完整正文，使用 markdown。必须写全结论、关键依据与用户接下来"
            "可以执行的动作，不要只写摘要，也不要逐字段复述结构化数据。"
        )
    )
    data: SchemaT = Field(description="结构化产物，字段与下方结构定义完全一致")


@cache
def envelope_for(schema: type[SchemaT]) -> type[SubagentReply[SchemaT]]:
    """把业务 Schema 包装成双轨信封。

    Pydantic 每次对泛型模型取下标都会新建一个类，而本函数在每次模型调用组装
    提示词时都会命中，因此必须缓存：否则每个请求都会白造一批模型类。
    """

    return SubagentReply[schema]