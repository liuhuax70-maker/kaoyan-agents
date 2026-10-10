"""多角色协作层（CrewAI）。

与 LangGraph 的分工：LangGraph 负责状态机编排与并行扇出，
CrewAI 负责需要角色对抗与多轮协商的协作场景。
"""

from app.crews.llm import KaoyanCrewLLM
from app.crews.review import (
    build_review_crew,
    plan_review_context,
    review_plan,
    review_plan_locally,
    review_plan_with_crew,
)

__all__ = [
    "KaoyanCrewLLM",
    "build_review_crew",
    "plan_review_context",
    "review_plan",
    "review_plan_locally",
    "review_plan_with_crew",
]
