# 后端重构计划：Subagents 架构收敛与产品化

> 状态：**阶段 0–5 已实施**（本文保留为设计与决策记录，不再随代码演进而逐条更新）
> 范围：先后端，前端在阶段 5 单独排期
> 分支建议：`refactor/subagents-v2`
>
> 实施过程中与本文有三处偏差（不新增 alembic 迁移、`thread_id` 改为一轮一条、
> 额外声明 `psycopg[binary]`），原因记录在 [code-knowledge-map.md](code-knowledge-map.md) 阶段 4。

---

## 一、背景与目标

系统当前是 FastAPI + LangGraph + LangChain + CrewAI 四件套，编排模式为 Subagents（聊天 Agent 通过工具调度 7 个子智能体）。
该模式本身要保留，但四类问题必须先解决：

| 问题 | 具体表现 |
| --- | --- |
| 框架重叠 | LangGraph 只搭了 3 个线性节点，收益极低；CrewAI 仅服务「计划评审」一个场景；LangChain 抽象层只有 `ChatOpenAI` 一处实质用处 |
| 回答质量 | 聊天 Agent 自己的回答被丢弃，用户最终看到的是两次压缩后的摘要 |
| 难维护 | `offline.py` 764 行 + `stub.py` 构成第二套必须同步维护的实现；13 个测试模块依赖它 |
| 非产品级 | 无多轮记忆、无真流式、计划直接覆盖落库无确认 |

**目标**：单一编排框架、单条执行路径、回答正文由模型直接生成、具备会话记忆 / token 流式 / 计划确认三项产品能力。

---

## 二、根因诊断（三条，均有代码依据）

### 1. 聊天 Agent 的回答被丢弃 —— 回答质量的头号根因

[chat_agent.py:243-289](backend/app/workflows/chat_agent.py#L243-L289) 中模型做完全部工具调用后，其输出文本从未被使用。
代码转而调用 [compose_summary()](backend/app/workflows/nodes.py#L420-L430) 再发**第二次** LLM 请求，生成 `ChatSummary`（仅 `summary` / `key_points` / `next_actions` 三个字段），
再由 [reply_text()](backend/app/schemas/workflow.py#L83-L113) 渲染成回复正文。

用户看到的答案经过两次压缩：

```
子智能体完整产出  ──① brief 压缩──▶  title + summary + 前 3 条 highlights
                  ──② JSON schema──▶  summary + key_points + next_actions
```

[chat_agent.py:84-95](backend/app/workflows/chat_agent.py#L84-L95) 的 `brief` 只取 `title`/`summary`/`highlights[:3]`，
答疑讲师的 `steps` / `pitfalls` / `followups`（[TutoringAnswer](backend/app/schemas/tutoring.py)）在到达用户前基本被丢光。

### 2. 完全没有多轮记忆

[chat_agent.py:225-230](backend/app/workflows/chat_agent.py#L225-L230) 构造的消息只有「考生画像 + 当前计划 + 本次输入」。
历史对话不存在，追问「那第二点展开说说」时模型失忆。

### 3. 「流式」是假的

[runner.py:212](backend/app/workflows/runner.py#L212) 用 `stream_mode="values"` 在**每个节点跑完之后**对比状态增量。
图只有 3 个线性节点，SSE 实际只在节点边界吐事件，最终回答整块到达。
前端的「调用链」靠 `event.node` 字符串匹配 [ChatPanel.tsx:96-108](frontend/src/components/ChatPanel.tsx#L96-L108) 的硬编码 `TOOL_LABEL` 推断。

### 附带清理项

- `COORDINATOR_ROLE` + `decide_intent` 在真实路径下已是死代码 —— [_describe_intent](backend/app/workflows/chat_agent.py#L292-L302) 直接返回硬编码 `"chat"`。
- `WorkflowResult.intent` / `confidence` 随之失去意义。

---

## 三、目标架构

### 决策记录

| 决策项 | 结论 |
| --- | --- |
| 框架收敛 | **LangGraph 为唯一编排层**；砍掉 CrewAI；LangChain 收缩为只用 `langchain-openai` 的 `ChatOpenAI` 做模型适配 |
| 子智能体输出 | **结构化 + 自然语言正文双轨**；取消 `compose_summary` 二次总结 |
| 产品化能力 | 真·token 流式、多轮会话记忆、计划落库前人工确认（不做用户反馈回流） |
| 离线降级 | 生产代码中**彻底删除**；测试用 `tests/fakes.py` 的假模型 monkeypatch 注入 |

### 编排拓扑（阶段 4 完成后）

```
START
  └─▶ prepare_context          载入画像 / 计划 / 会话历史
        └─▶ chat_agent         工具调用循环；最终回答逐 token 流出
              ├─(conditional)─▶ review_plan     有 plan_draft 且开启评审时
              └────────────────▶ confirm_plan    有 plan_draft / plan_revision 时 interrupt
                                  └─▶ finalize ─▶ END
```

- 评审与确认走 LangGraph 条件边，取代原 CrewAI 与「服务层直接落库」。
- `thread_id` 由 checkpointer 负责归档与恢复；**实际不用 `conversation_id` 本身**，
  而是 `"{conversation_id}:{message_id}"`（一轮对话一条线程）。
  原因见 [code-knowledge-map.md](code-knowledge-map.md) 阶段 4 的「两处与计划的偏差」：
  线程状态是累加的，复用会话 ID 会让上一轮的产出与待确认计划续到这一轮。

### 子智能体返回信封

```python
# backend/app/schemas/subagent.py（新增）
class SubagentReply(BaseModel, Generic[T]):
    narrative: str   # 面向用户的完整 markdown 正文，直接作为工具结果回灌聊天 Agent
    data: T          # 原有结构化产物（PlanDraft / TutoringAnswer / ...），驱动落库与结构化卡片
```

工具回灌给聊天 Agent 的内容由「压缩的 brief」变为**完整 narrative**；
`render_*()` 从「生成正文」降级为「仅在模型未给 narrative 时兜底」。

---

## 四、分阶段实施

每个阶段独立可合并、可验证。**阶段顺序不可调换**：4 依赖 3 的流式管线，3 依赖 2 的状态字段。

### 阶段 0：地基（删降级路径 + 评审迁出 CrewAI）

**删除文件**
- `backend/app/llm/stub.py`
- `backend/app/llm/offline.py`（约 764 行）
- `backend/app/crews/`（整包：`__init__.py`、`review.py`、`llm.py`）

**修改文件**
| 文件 | 改动 |
| --- | --- |
| `backend/app/llm/__init__.py` | 导出表去掉 `StubChatModel` / `build_offline_payload` / `supports` |
| `backend/app/llm/factory.py` | `build_chat_model` 删 `stub` 分支；`invoke_agent_task` 删兜底重试，失败即抛 |
| `backend/app/core/config.py` | `LLMProviderName` 与 `PROVIDER_DEFAULTS` 去掉 `"stub"`；`default_provider` 改为 `"deepseek"`；`WorkflowSection` 去掉 `plan_review_process` |
| `backend/app/workflows/chat_agent.py` | 删 `_run_offline`、`provider == "stub"` 分支、异常回退分支 |
| `backend/app/workflows/nodes.py` | 删 `_stub_context`、`DEFAULT_AGENTS`、`MAX_AGENTS`、`decide_intent`、`compose_summary` |
| `backend/app/prompts/catalog.py` | 删 `COORDINATOR_ROLE` |
| `backend/app/llm/tasks.py` | 删 `intent_routing`、`chat_summary` 任务与对应 schema |
| `backend/app/agents/nudge.py` | 去掉 stub 引用 |
| `backend/app/knowledge/embeddings.py` | `StubEmbedder` 迁至 `tests/fakes.py`，生产只保留 ollama / openai / dashscope |
| `backend/pyproject.toml` | 删 `crewai` 依赖 |

**评审迁移**（保持功能不回退）：新增 `review_plan` 图节点，复用现有 `PlanReviewResult` schema 与 `REVIEWER_ROLE`，由 `chat_agent → review_plan` 条件边触发；原 `_attach_plan_review`（[runner.py:97-113](backend/app/workflows/runner.py#L97-L113)）删除。

**测试**：新建 `backend/tests/fakes.py`（`FakeChatModel(BaseChatModel)`，按脚本返回文本或工具调用）；`conftest.py` 去掉 `LLM__DEFAULT_PROVIDER=stub`，改为 monkeypatch 注入；
`tests/test_crews.py` 改写为 `review_plan` 节点测试；`tests/test_llm.py` / `test_api.py` / `test_knowledge.py` 相应适配。

### 阶段 1：回答质量（双轨输出）

- 新增 `backend/app/schemas/subagent.py`：`SubagentReply[T]` 泛型信封。
- `backend/app/llm/factory.py`：新增 `invoke_subagent_task()`，返回 `(narrative, data)`。
- `backend/app/workflows/nodes.py`：7 个 `_run_*` 统一改为产出 `narrative` + `data`。
- `backend/app/workflows/chat_agent.py`：工具回灌内容改为完整 narrative；**删除 `compose_summary` 调用**，最终回答直接取模型自身输出。
- `backend/app/schemas/workflow.py`：`WorkflowResult` 新增 `reply: str`；`reply_text()` 返回 `self.reply`（无值时兜底拼 `outputs`）；移除 `summary` 字段。
- `backend/app/workflows/render.py`：删 `render_summary`，`render_*` 保留为兜底。
- `backend/app/schemas/revision.py`：删 `ChatSummary`。

### 阶段 2：多轮会话记忆

- `backend/app/workflows/state.py`：`WorkflowState` 新增 `history: list[dict[str, str]]`。
- `backend/app/services/conversations.py`：新增 `load_history(session, conversation_id, limit)`；`ChatContext` 新增 `history`；`start_conversation` 中加载（取当前用户消息**之前**的记录）。
- `backend/app/workflows/runner.py`：`build_initial_state` / `run_workflow` / `stream_workflow` 增加 `history` 参数。
- `backend/app/workflows/chat_agent.py`：`_chat_messages` 在 system 之后插入历史（`HumanMessage` / `AIMessage`）。
- `backend/app/core/config.py`：`WorkflowSection` 新增 `history_limit`（默认 20 条）与 `history_char_budget`。

复用 `AgentMessage` 表（`content` 已是 markdown 正文，`role` 区分 USER / ASSISTANT），**无需新表**。

### 阶段 3：真·token 流式

- `backend/app/workflows/chat_agent.py`：最终回答改用 `model.astream()`，通过 LangGraph 的 `get_stream_writer()` 推 `{"type": "token", "text": ...}`。
- `backend/app/workflows/runner.py`：`stream_workflow` 改为 `astream(stream_mode=["custom", "values"])` —— `custom` 收 token，`values` 收 `outputs` / `events` 增量。
- `backend/app/services/conversations.py`：透传 `token` 事件。
- **取舍**：v1 只对聊天 Agent 的最终回答做 token 流式；子智能体阶段（structured JSON）不适合逐字输出，仍用 `progress` 事件。计划生成这类长任务的体感优化留待后续。

### 阶段 4：计划落库前人工确认

- **新增依赖**：`langgraph-checkpoint-postgres`（生产）、`langgraph-checkpoint-sqlite`（开发/测试），外加 `psycopg[binary]` —— 前两者只依赖纯 Python 的 `psycopg`，缺了 binary extra 会在没有 libpq 的机器上直接 import 失败。
- `backend/app/workflows/graph.py`：编译时挂 checkpointer；新增 `confirm_plan` 节点，对存在 `plan_draft` / `plan_revision` 的状态调用 `langgraph.types.interrupt()`。
- `backend/app/services/conversations.py`：`stream_chat` 捕获 `__interrupt__`，发 `{"type": "awaiting_confirmation", ...}`；`AgentConversation.status` 置为 `awaiting_confirmation`（现有 `String(32)` 字段可直接承载）。
- `backend/app/api/routes/chat.py`：新增 `POST /api/chat/confirm`，接收 `{conversation_id, approve, feedback?}`，以 `Command(resume=...)` 恢复图。
- `backend/app/schemas/api.py`：新增 `ChatConfirmRequest`。
- **实施偏差：不新增 alembic 迁移。** 检查点表改由 saver 自带的 `setup()` 建
  （详见 [code-knowledge-map.md](code-knowledge-map.md) 阶段 4）：表的 DDL 属于
  `langgraph-checkpoint` 的内部实现并随其版本演进，手抄进迁移必然漂移；
  开发用的 SQLite 检查点又落在独立的文件里，本就不在 alembic 管辖范围内。

---

## 五、破坏性契约变更（阶段 5 已全部对齐）

后端本次改变了对外约定，前端在阶段 5 一并处理完毕：

| 变更 | 影响 | 落地 |
| --- | --- | --- |
| SSE 新增 `token` 事件 | [sse.ts](frontend/src/lib/sse.ts) 支持增量追加；[ChatPanel.tsx](frontend/src/components/ChatPanel.tsx) 流式渲染 | 已做 |
| SSE 新增 `awaiting_confirmation` 事件 + `POST /api/chat/confirm` | 新增确认交互 | 已做，另加 SSE `tool_call` 帧 |
| 移除 `meta.intent` / `confidence` | [types.ts](frontend/src/lib/types.ts) 与 `toTurns` | 已做，且后端同步删除（`confidence` 恒为 0，`intent` 与 `tool_calls[0].agent` 恒等） |
| `ChatResponse.summary` 移除，改用 `reply` | 契约类型同步 | 已做（阶段 1） |
| 调用链不应再由 `event.node` 猜 | 后端直接给出结构化 `tool_calls`（改为权威来源） | 已做：聊天 Agent 在调起工具时推 `tool_call` 帧 |
| 无 markdown 渲染器 | 后端正文现在就是 markdown，前端必须引入渲染器 | 已做：`react-markdown` + `remark-gfm`，排版规则在 `globals.css` 的 `.answer-body` |

---

## 六、验证方式

**每阶段**
```bash
cd backend && pytest -q          # 全部 106 个用例须通过（阶段 0 后用例总数会减少）
cd backend && ruff check app tests
```

**端到端（需真实 `DEEPSEEK_API_KEY`）**
```bash
# 1. 起基础设施
docker compose up -d
# 2. 起后端
cd backend && uvicorn app.main:app --reload --port 8000
# 3. 冒烟
python scripts/smoke_api.py
```

**分阶段验收点**
- 阶段 0：无 key 启动服务应**明确报配置错误**（而非静默降级）；有 key 时对话可用。
- 阶段 1：答疑类问题，回答中应能看到解题步骤与易错点原文（对照当前版本应显著更完整）。
- 阶段 2：同一会话内追问「第二点再展开」，模型能正确指代。
- 阶段 3：`curl -N` 观察 `/api/chat/stream`，应出现连续 `token` 帧而非一次性 `done`。
- 阶段 4：生成计划后流程暂停并返回待确认内容；调用 `/api/chat/confirm` 后才写库。

---

## 七、风险与取舍

| 风险 | 缓解 |
| --- | --- |
| 阶段 4 把 interrupt + 自定义流式 + 工具调用循环三者叠加，调试成本高 | 严格按 0→1→2→3→4 顺序，每阶段可独立合并 |
| 删除 stub 后，无 key 的开发/CI 环境无法跑对话 | 阶段 0 即建立 `tests/fakes.py`；本地开发改用 DeepSeek 或 Ollama（`LLM__DEFAULT_PROVIDER=ollama`） |
| checkpointer 表与现有迁移体系并存 | 改由 saver 的 `setup()` 建表（见「阶段 4」的实施偏差），既有迁移一字未动 |
| 用户不答复确认，会话永远停在待确认上 | 确认能力与 checkpointer 同开关；会话状态由 `awaiting_confirmation` 显式承载，前端可据此提醒 |
| 评审从 CrewAI 迁到图节点后质量变化 | 阶段 0 即完成迁移并对比同一份计划的评审输出 |
| 子智能体输出信封增加一层，可能降低 JSON 解析成功率 | 信封走现有 `invoke_structured` 重试机制（[structured.py:91-136](backend/app/llm/structured.py#L91-L136)），并把解析失败计入可观测性 |

---

## 八、待确认项

1. ~~`docs/` 目录与 README 的架构图需要同步更新~~ —— **阶段 5 已更新**：README 的编排拓扑、
   三项产品能力与 SSE 事件表改为与实际一致，并补了 `## 文档` 索引。
2. `backend/app/knowledge/corpus.py` 目前是 9 篇硬编码语料，是否替换为真实考研资料 —— 属内容工作，未纳入本计划。
3. ~~前端阶段 5 是否同时补齐 markdown 渲染器与调用链展示~~ —— **已做**：markdown 渲染器
   已引入，调用链改由后端 `tool_call` 帧给出。

---

## 九、产品化增量（阶段 6–10）

上面八节处理的是「架构收敛」：让回答质量、记忆、流式与确认这四件事真的成立。
阶段 6–10 是其后的一轮**产品增量** —— 用户提交了产品规格，要求系统真正承担考研党的
三件事：**择校、制定计划、陪伴**，并附一条硬约束：**不能替用户做决定**。

这一轮没有推翻任何一节的设计，而是在同一套 Subagents 编排上加能力。三处值得记下的判断：

| 规格要求 | 落地方式 | 为什么这样做 |
| --- | --- | --- |
| 给出**多所**院校与各自优劣势，不替用户拍板 | 四层结构约束（`extra="forbid"` + 列表长度 + 机械不变式 + 散文），候选落 `tracked_schools` 表，只有用户的显式动作才写回 `ExamTarget` | 「没替用户决定」必须**可审计**。只写提示词禁令是散文，无从验证；状态迁移 + 唯一写回入口才让它在数据上可区分 |
| 每天返回院校情况 + **可点击的链接** | 第五类提醒 `school_brief`；核验入口由 `official_entry_links` 确定性拼出，不经过模型 | 让模型写院校域名等于请它编造链接。只给研招网与搜索跳转 URL，最坏是「多跳一次搜索」而不是「指向抢注域名」 |
| 计划像**课程表**那样列出 + 最右列今日目标 | `StudyTask.slot` + `services/scheduling.py` 统一排序与时段分配；前端 `lib/timetable.ts` 纯函数算今日目标 | 中文字典序不等于时间顺序，裸 `order_by(slot)` 是静默错的排序；今日目标的口径要能被单测，否则「当时算的」与「界面上看到的」会漂移 |
| 无需太严格执行，可以**动态**规划 | 逾期任务一键顺延（按钮 + 聊天同一路径）；`COACH_ROLE` 话术改邀请式；断签触发口径改为「连续零投入」 | 保留全部统计，只换框架。原口径「距上次学习多少天」对自律度低的用户读起来就是催办 |

三处迁移的风险排序值得记下来：**给既有枚举加成员是最贵的一种**（`ReminderType`，
SQLite 下必须整表重建），新实体自声明约束名最便宜（`tracked_schools`），
加普通可空列居中（`study_tasks.slot`）。结论写成一条纪律：**除非必要，不给既有枚举加成员**。

逐阶段的代码 ↔ 知识点对照、以及每处刻意取舍的原因，见
[code-knowledge-map.md](code-knowledge-map.md) 阶段 6–10 各节。