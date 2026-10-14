# 代码 ↔ 知识点对照表

重构产出的每一块代码所对应的知识点索引，用于复习与答辩自检。

## 关于「文档定位」列的说明

本表引用的课程文档**目前还没有进仓库**，目标路径是 `docs/knowledge/langgraph-course.md`。
在该文件落库之前，定位只写到**章级**（例如「第5章 LangGraph·基本概念」），
不写小节名与序号 —— 凭记忆编造锚点比不写锚点更糟。

文档落库后需要做一次校准：通读真实标题，把定位补到小节级，并核对每条知识点确实在那节讲过。

> 若该文档是第三方课程讲义，公开前请先确认授权；不确定就改为本地存放并加入 `.gitignore`。

## 阶段 0：地基（删降级路径 + 评审迁出 CrewAI）

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `workflows/state.py` | 状态定义 | State + Reducer | 第5章 LangGraph·基本概念 | 同一字段被多个分支写入时，合并规则由字段上的 `Annotated[type, reducer]` 决定，而不是由写入方决定 |
| `workflows/state.py` | 状态定义 | 字段取舍 | 第5章 LangGraph·基本概念 | 「下游需要就存、能推导就不存」；带累加 reducer 时节点只返回新增部分，不必读改写整份列表 |
| `workflows/state.py` | 状态定义 | 状态的纯净性 | 第5章 LangGraph·基本概念 | State 只承载数据、不做数据库读写，图因此可以脱离数据库单测 |
| `workflows/graph.py` | 图装配 | `StateGraph` 装配与编译 | 第5章 LangGraph·基本概念 | 图结构在编译期固定，节点是纯函数，拓扑可以被静态描述出来 |
| `workflows/graph.py` | 图装配 | 条件边 vs 无条件边 | 第5章 LangGraph·六种编排模式 | `add_conditional_edges` 把「下一步走哪」抽成独立函数，路由逻辑可单独测试 |
| `workflows/graph.py` | 图装配 | 开关写进 State | 第5章 LangGraph·基本概念 | 运行期开关要落在 State 里由条件边读取，而不是在节点内回头查配置，否则状态回放出的路径不一致 |
| `workflows/nodes.py` | 评审节点 | Orchestrator-Worker | 第5章 LangGraph·六种编排模式 | 编排者只负责派活与收活，专业能力下沉到 worker，新增 worker 不改编排逻辑 |
| `workflows/nodes.py` | 评审节点 | 生成与评审分离 | 第5章 LangGraph·六种编排模式 | 同一段上下文里既当作者又当裁判，模型挑不出自己的问题，因此拆成两个节点两次调用 |
| `workflows/chat_agent.py` | 调度入口 | Subagents 模式 | 第3章 Agent进阶·Multi Agent | 主 Agent 不实现任何专业能力，只持有「派给谁」的工具；子智能体之间互不可见，上下文隔离靠工具边界 |
| `workflows/chat_agent.py` | 调度入口 | `bind_tools` + `ToolMessage` 回灌 | 第2章 LangChain核心组件·工具调用 | 模型出参数 → 本地执行 → 结果作为一条消息回到历史 → 模型据此继续决策，循环由轮次上限兜底 |
| ~~`workflows/chat_agent.py`~~ | ~~统一总结~~ | ~~LLM 节点~~ | ~~第5章 LangGraph·基本概念~~ | **阶段 1 已删除**：`_compose_summary` 与 `ChatSummary` 一起移除，最终回答改由模型自己给出 |
| `workflows/runner.py` | 流式执行 | `stream_mode` 语义 | 第5章 LangGraph·基本概念 | `values` 模式在每次状态更新后推一份完整 State；配合累加 reducer，用「本次长度 − 上次长度」就能切出增量 |
| `workflows/runner.py` | 流式执行 | 默认值与显式开关的分工 | 第5章 LangGraph·基本概念 | 配置默认值在入口处折算成显式状态字段，图内部只认状态，不认配置 |
| `llm/factory.py` | 模型适配 | OpenAI 兼容协议 | 第2章 LangChain核心组件·模型 | DeepSeek / Ollama / OpenAI 的差异只在 `base_url` 与 `model` 名，适配成本集中在配置而非代码 |
| `llm/factory.py` | 结构化输出 | 结构化输出 + 错误回灌重试 | 第2章 LangChain核心组件·结构化输出 | 用 Pydantic schema 约束模型输出；解析失败时把错误信息回灌给模型重出，而不是就地吞掉 |
| `llm/factory.py` | 失败语义 | 不做静默降级 | 第2章 LangChain核心组件·模型 | 配置缺失或调用失败一律抛出：宁可请求失败暴露问题，也不要用假结果掩盖故障 |
| `knowledge/embeddings.py` | 向量化 | Embedding 与对话模型分离配置 | 第4章 RAG Agent·构建知识库 | DeepSeek 不提供 embedding 接口，因此向量化是一套独立配置；三家提供方同样共用 `/embeddings` 协议 |
| `tests/fakes.py` | 测试策略 | 假模型的替身位置 | 第2章 LangChain核心组件·模型 | 假件替换在 I/O 边界（工厂与网络调用），而不是在业务层加分支，因此真实代码路径全部保留 |
| `tests/fakes.py` | 测试策略 | 读提示词的等价性 | 第2章 LangChain核心组件·模型 | 真实模型也只能看到提示词，假模型读同一份提示词才谈得上等价；绕过提示词直接拿业务对象就失去了测试意义 |

## 阶段 1：回答质量（双轨输出）

本阶段解决的问题：聊天 Agent 做完全部工具调用后，它自己的输出文本从未被使用，
代码转而再发一次模型请求生成三字段的 `ChatSummary`。子智能体的完整产出在两个环节被
压缩两次，答疑讲师的解题步骤与易错点到达用户前基本丢光。

做法：子智能体一次调用同时给出「面向用户的正文」与「驱动落库的结构化数据」，
正文原样作为工具结果回灌，最终回答直接取模型自己的输出。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `schemas/subagent.py` | 双轨信封 | 结构化输出的双轨信封 | 第2章 LangChain核心组件·结构化输出 | 同一次调用既产出驱动落库的数据、也产出面向用户的完整正文，模型只调一次，不再需要「先结构化、再二次总结」那道会把内容压掉的工序 |
| `llm/tasks.py` | 任务契约 | 提示词契约与解析契约同源 | 第2章 LangChain核心组件·结构化输出 | 输出模型只登记一处，模板渲染与结果解析都从同一个函数取值，格式与解析逻辑不可能各自漂移 |
| `llm/factory.py` | 模型适配 | 双轨调用的拆封位置 | 第2章 LangChain核心组件·结构化输出 | 「信封 → (正文, 数据)」的拆封收在适配层，业务层只看到两个普通值，不感知信封的存在 |
| `prompts/templates.py` | 提示词 | 输出契约自动注入 | 第2章 LangChain核心组件·结构化输出 | 提示词里的输出结构由 Schema 渲染而来，提示词与 Schema 不可能不同步 |
| `prompts/context.py` | 提示词 | JSON Schema 压缩与字段陷阱 | 第2章 LangChain核心组件·结构化输出 | 剥掉无信息量的 `title` 注解以压缩提示词体积，但必须区分「注解式 title」与真名字段叫 title 的属性 |
| `workflows/nodes.py` | 子智能体处理器 | 节点与处理器的分工 | 第5章 LangGraph·基本概念 | 只有图节点读写 State 并由图调度；七个处理器由聊天 Agent 在自己的循环里调用，因此可以自由改签名而不影响图拓扑 |
| `workflows/chat_agent.py` | 调度入口 | 完整正文回灌 | 第2章 LangChain核心组件·工具调用 | 回灌进 `ToolMessage` 的是子智能体的完整正文而非摘要，模型作答时看得到解题步骤与易错点原文 |
| `workflows/chat_agent.py` | 错误处理 | 错误回灌给 LLM | 第3章 Agent进阶·工具可靠性 | 工具抛错不是流程中断信号，而是一条要交回模型的消息；模型据此可改派工具或如实告知用户 |
| `workflows/chat_agent.py` | 循环控制 | 自主循环的硬边界 | 第3章 Agent进阶·Multi Agent | 循环何时结束由模型决定，代码就必须兜住「模型永远不停」；触边后降级为一次不带工具的调用 |
| `workflows/chat_agent.py` | 结果合并 | 状态字段的 reducer 契约 | 第5章 LangGraph·基本概念 | 带 `operator.add` 的字段由节点返回本回合增量，累加交给 reducer，节点不读改写整份列表 |
| `schemas/workflow.py` | 结果模型 | LLM 节点的输出即最终产物 | 第2章 LangChain核心组件·模型 | 模型用自然语言给出的回答不该被确定性代码再压缩一遍，代码只在模型没开口时兜底 |
| `agents/nudge.py` | 能力复用 | 一主一从的双轨封装 | 第2章 LangChain核心组件·结构化输出 | 同一任务被两条链路消费时，主实现产出双轨，只取数据的那条链路做一次解包，提示词仍只有一份 |
| `tests/fakes.py` | 测试策略 | 假模型的等价性 | 第2章 LangChain核心组件·模型 | 替身要与真实模型消费同一份输入（提示词）并产出同形状的输出，否则测试验证的是假件的想象而不是真实链路 |

### 本阶段的验证点

- `tests/test_workflow.py::test_tutoring_reply_keeps_steps_and_pitfalls` 直接断言
  答疑回答里逐字包含 `TutoringAnswer.steps[0]`、`pitfalls[0]`、`followups[0]` ——
  这正是「回答质量」这条线此前丢掉的内容。
- `test_plan_request_calls_planner_and_breakdown_tools` 断言两个子智能体的正文小节
  都进入了最终回答。

### 关于计划 §2.5（工具签名调整）的落地说明

计划原本打算把工具改成「只收 `runtime`、从 `runtime.state` 读业务上下文」的写法。
实际结论：**该质量目标在既有代码中已经达成**，但**未采用 `ToolRuntime` 机制**。

- 已达成：工具 schema 只暴露 `instruction` 一个参数，考生画像与计划由
  `_to_request(state, instruction)` 从图状态注入，模型无法（也不需要）转述业务上下文。
- 未采用：`ToolRuntime` 只由 `ToolNode` 注入 —— 实测 `langgraph` 1.2.14 已提供
  `langgraph.prebuilt.ToolRuntime`，但直接 `await tool.ainvoke(tool_call)` 会因
  `runtime` 字段缺失而校验失败。要用上它，必须把聊天 Agent 从「节点内的 for 循环」
  改成 `chat_agent ⇄ ToolNode` 的条件边回环，属于**拓扑改造**而非签名调整。

结论：保留现有的声明式注册表 + 节点内循环，把「回环化」留给后续阶段评估。
本阶段不为此改动图拓扑，以免与阶段 4（interrupt + checkpointer）同时动同一处结构。

## 阶段 2：多轮会话记忆

本阶段解决的问题：聊天 Agent 的消息只有「考生画像 + 当前计划 + 本次输入」，
同一会话里追问「第二点再展开」时，模型看不到上一轮说了什么跟第二点。

做法：复用 `AgentMessage` 表作为记忆载体——一行消息既是回放给前端的记录，
也是下一轮拼进提示词的上文，不需要新建记忆表。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `services/conversations.py` | 记忆读取 | 记忆的存储形态 | 第3章 Agent进阶·记忆 | 会话记录本身就是记忆，不必另建表；但只取用户与助手的正文，工具轨迹与结构化产出留在 `meta`/`payload` 里供回放，不占上下文预算 |
| `services/conversations.py` | 记忆读取 | 「上文」不含本次提问 | 第3章 Agent进阶·记忆 | 历史要按消息 id 切在本次提问之前，否则模型会看到两份当前问题 |
| `prompts/context.py` | 预算控制 | 上下文窗口的预算控制 | 第3章 Agent进阶·记忆 | 历史不能无节制地拼进提示词，要按字符预算从最旧的一轮开始丢，且永远保住最近一轮 |
| `workflows/state.py` | 状态定义 | 对话记忆的载体 | 第3章 Agent进阶·记忆 | 多轮上文是一份「状态输入」而非节点的私有缓存，由调用方备好再喂进来，图本身不读数据库 |
| `workflows/chat_agent.py` | 提示词组装 | 记忆的注入位置 | 第3章 Agent进阶·记忆 | system 定人格、历史给上文、human 是本次输入，顺序固定；历史以真实消息序列插入而不是塞进一段文本块，指代才稳 |
| `workflows/runner.py` | 入口 | 记忆的透传 | 第3章 Agent进阶·记忆 | 记忆从服务层一路显式透传到初始状态，中间没有隐式全局，因此「有记忆」与「无记忆」两种跑法都能测 |
| `tests/fakes.py` | 测试策略 | 假模型的 spy 视角 | 第2章 LangChain核心组件·模型 | 假模型记录收到的每一份请求，用例才能断言「提示词里到底有什么」，而不是只断言回答看起来对 |

### 本阶段的验证点

- `tests/test_services.py::test_load_history_returns_previous_turns_in_order` ——
  历史的时间正序、以及「排除本次提问」。
- `tests/test_services.py::test_load_history_keeps_the_nearest_turns_and_drops_tool_rows` ——
  条数上限从最近往回取，工具与系统消息不进上下文。
- `tests/test_workflow.py::test_followup_turn_sees_previous_question_and_answer` 与
  `tests/test_api.py::test_followup_chat_carries_previous_answer` —— 直接断言
  上一轮的问与答出现在模型的输入消息里（`contents[1]` / `contents[2]`）。
- `tests/test_workflow.py::test_trim_history_*` —— 预算裁剪的边界：最近一轮即使单独
  超预算也保留，空白轮次被跳过。

### 一处实现取舍

预算裁成两处、各管一段：

- `load_history` 只管 SQL 层的 `LIMIT`（`workflow.history_limit`，默认 20 条）——
  避免把上万行历史捞进内存；
- `trim_history` 只管字符预算（`workflow.history_char_budget`，默认 4000）——
  它属于提示词组装的关注点，所以放在 `prompts/context.py`。

两者刻意不重叠，避免同一个上限在两个地方各写一遍。

## 阶段 3：真 token 流式

本阶段解决的问题：原来的「流式」是假的——`stream_mode="values"` 只在节点跑完后对比状态
增量，而图只有三个线性节点，SSE 实际只在节点边界吐事件，最终回答整块到达。

做法：聊天 Agent 的每一轮模型调用改走 `astream`，边收增量边通过 `get_stream_writer()`
把 `{"type": "token", "text": ...}` 推给调用方；`runner` 同时订阅 `custom` 与 `values`
两条流。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `workflows/chat_agent.py` | 流式输出 | 自定义流 `get_stream_writer` | 第5章 LangGraph·流式 | 节点内部的增量不走 State，而是通过写入器直接推给调用方；State 仍只在节点边界整块更新，两条通道互不干扰 |
| `workflows/chat_agent.py` | 流式输出 | 增量消息的合并 | 第5章 LangGraph·流式 | `astream` 吐的是 `AIMessageChunk`，要边收边用 `+` 合并成完整消息回填历史，否则 `tool_calls` 会丢 |
| `workflows/runner.py` | 流式执行 | 多模式流 `stream_mode=["custom","values"]` | 第5章 LangGraph·流式 | 同一个图可以同时订阅多种流，传模式列表时每条产出都带模式标签，按标签分流即可 |
| `services/conversations.py` | 流式接口 | 事件透传与权威值 | 第5章 LangGraph·流式 | 增量帧只是「过程中的样子」，`done` 帧里的 `reply` 才是权威值，前端应以它收尾 |
| `tests/fakes.py` | 测试策略 | 假件必须真分块 | 第2章 LangChain核心组件·模型 | 若沿用基类「一次吐一整条」的兜底，连续 token 帧这条验收永远假通过，因此假模型要按固定粒度切分 |

### 本阶段的验证点

- `tests/test_api.py::test_stream_chat_emits_incremental_tokens` —— 解析 SSE 帧，
  断言 `token` 帧多于一条、拼起来等于 `done` 帧的 `reply`，且 `done` 是最后一帧。
- `tests/test_workflow.py`、`tests/test_observability.py` 的既有流式用例继续通过，
  说明 `values` 通道的增量切片没被多模式订阅破坏。

### 一处已知取舍

工具轮若「先垫一句再调工具」，垫的正文会先作为 token 推出去，但它不计入最终 `reply`。
真实提供方在绑定工具时通常只回 `tool_calls` 不回正文，因此实践中很少触发；
即便触发，用户看到的是「让我先查一下…」这类过渡语，属于可接受的体验，
而 `done` 帧的 `reply` 始终是权威值。

## 阶段 4：计划落库前人工确认

本阶段解决的问题：计划是模型生成的，却由代码直接写进数据库——用户看到成品时，
木已成舟。而 LangGraph 的 `interrupt` 恰好是为此准备的：图能在「生成完、还没落库」
这个点上停下来，把控制权交回调用方，用户答复后再从原处继续。

做法：给图挂上 checkpointer，在 `review_plan` 与 `finalize` 之间插入 `confirm_plan`
节点；暂停时只落消息不落计划，恢复时用同一个 `thread_id` 带回用户答复。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `workflows/checkpoint.py` | 检查点存储 | Checkpointer | 第5章 LangGraph·人工确认 | 状态本可只活在内存里，挂上检查点后按 `thread_id` 归档，因此「暂停—恢复」才能跨请求成立 |
| `workflows/checkpoint.py` | 检查点存储 | 建表归属 | 第5章 LangGraph·人工确认 | 检查点表由库的 `setup()` 建并随库版本演进，手写一份 alembic 迁移只会与它的 DDL 漂移 |
| `workflows/graph.py` | 图装配 | 编译期挂载 checkpointer | 第5章 LangGraph·人工确认 | 传 checkpointer 才有暂停能力；不传就是一次直跑，绝大多数单测因此不依赖任何持久化 |
| `workflows/runner.py` | 入口 | `thread_id` 与运行配置 | 第5章 LangGraph·人工确认 | `thread_id` 被折进 `configurable` 配置，图按它归档状态、也按它把状态取回来 |
| `workflows/runner.py` | 入口 | `Command(resume=...)` 恢复 | 第5章 LangGraph·人工确认 | 恢复请求带回的是「用户答复」而不是新输入，因此已经跑过的聊天 Agent 不会重跑 |
| `workflows/runner.py` | 入口 | `__interrupt__` 保留键 | 第5章 LangGraph·人工确认 | 暂停载荷不是普通状态字段，而是库放在 `__interrupt__` 下的保留键，只认带 `kind` 的那种 |
| `workflows/nodes.py` | 确认节点 | interrupt 人工确认 | 第5章 LangGraph·人工确认 | `interrupt()` 暂停时状态入检查点，恢复时同一个调用原地返回用户答复，节点从这句之后继续 |
| `workflows/nodes.py` | 确认节点 | 驳回也要走完图 | 第5章 LangGraph·基本概念 | 「不落库」不等于「什么都不做」：草稿必须被清掉，否则服务层仍会照着状态写库 |
| `workflows/nodes.py` | 确认节点 | 确认对象与落库对象同源 | 第5章 LangGraph·基本概念 | 弹给用户确认的那份，就是真正会写库的那份（重排优先于修订），否则用户是在为一份不会被写入的东西点头 |
| `workflows/state.py` | 状态定义 | 开关写进 State | 第5章 LangGraph·基本概念 | `confirm_commit` 与 `enable_review` 同样是显式状态字段，确认节点只读状态、不回头查配置 |
| `services/conversations.py` | 服务层 | 一轮对话一条线程 | 第5章 LangGraph·人工确认 | 线程状态是累加的，复用线程会让上一轮产出泄进这一轮，还会把上一轮的待确认续过来 |
| `services/conversations.py` | 服务层 | 会话状态做闸门 | 第5章 LangGraph·人工确认 | 「已答复」记在会话状态上，重复点确认因此被挡在恢复之前，不会写出两份计划 |
| `schemas/workflow.py` | 结果模型 | 暂停也是一种结果 | 第2章 LangChain核心组件·模型 | 一次运行可能以「暂停」收尾，结果模型要能表达这件事，而不是让调用方从空字段里猜 |
| `tests/fakes.py` | 测试策略 | 内存检查点作为替身 | 第5章 LangGraph·人工确认 | 内存实现与真实实现在「按 `thread_id` 存取状态」上等价，换掉它，中断状态在用例之间天然隔离 |

### 本阶段的验证点

- `tests/test_api.py::test_plan_generation_waits_for_confirmation` —— 暂停时
  `/api/tasks` 为空、会话状态为 `awaiting_confirmation`；调 `/api/chat/confirm`
  之后才拿到 `plan_id`，任务才出现。这正是阶段 4 的验收标准。
- `tests/test_api.py::test_rejected_plan_is_never_written` —— 驳回后任务表仍为空，
  且同一会话再次确认返回 404（闸门已合上）。
- `tests/test_api.py::test_stream_chat_stops_at_the_confirmation_gate` —— 流式接口
  末帧是 `awaiting_confirmation` 而非 `done`，`token` 帧照旧逐字到达，且没有落库。
- `tests/test_checkpoint.py::test_workflow_pauses_and_resumes_on_the_real_checkpointer` ——
  **真实 SQLite 后端**（不是内存假件）上的暂停与恢复，证明装配好的检查点确实存得住状态。
- `tests/test_checkpoint.py::test_sqlite_checkpointer_is_built_and_set_up` ——
  后端选择与 `setup()` 建表。

### 三处与计划的偏差（记录原因）

**一、不新增 alembic 迁移。** 计划原本要在 `alembic/versions/` 里建检查点表。
实际做法是让 `get_checkpointer()` 调用 saver 自带的 `setup()` 建表：

- 检查点表的 DDL 属于库的内部实现，随 `langgraph-checkpoint` 版本演进，
  手抄一份到迁移里必然漂移（升级依赖后两份 DDL 就对不上了）；
- 开发用的是**另一个** SQLite 文件，本来也不在 alembic 的管理范围内。

**二、`thread_id` 不复用 `conversation_id`，而是一轮对话一条。** 计划写的是复用会话 ID，
实际用 `"{conversation_id}:{message_id}"`：

- 线程里的状态是**累加**的（`outputs` / `events` / `tool_calls` 都带 `add` reducer），
  同一会话第二轮会连上一轮的产出一起回吐；
- 更麻烦的是上一轮没答复的 `plan_draft` 会跟着续到这一轮，用户随手问一个别的问题
  也会被要求确认一份旧计划。

请求里仍然带着 `conversation_id`，待确认的 `thread_id` 由服务层写在消息 `meta` 里，
因此对外契约没变。

**三、除两个 langgraph 检查点包外，还显式声明 `psycopg[binary]`。**
实测 `langgraph-checkpoint-postgres` 只依赖纯 Python 的 `psycopg`，
后者在没有系统 libpq 的机器上 import 即失败（本机 Windows 与
`python:3.11-slim` 镜像都属此类，Dockerfile 装的 `build-essential` 并不含 libpq）。
不写这个 extra，生产一启用 PostgreSQL 检查点就会在启动时炸。

## 阶段 5：收尾（前端对齐新契约 + README / 文档索引）

后端的契约在阶段 1 / 3 / 4 变了三轮，前端一直停在旧契约上，本阶段把两端对齐。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `workflows/chat_agent.py` · `_run_tool_calling` | 调用链 | 自定义流承载结构化事件 | 第5章 LangGraph·流式 | 节点内部除正文增量外还能推任意结构；调用链由 `tool_call` 帧直接给出，调用方不必再拿事件里的 node 名反推调了哪个工具 |
| `frontend/src/components/ChatPanel.tsx` · `send` | 流式渲染 | 自定义流在客户端的形态 | 第5章 LangGraph·流式 | 增量帧是累积拼接而非覆盖，拼起来的正文应恰好等于收尾帧的 `reply`——客户端只有按这条不变量写，才不会漏字或重复 |
| `frontend/src/components/ChatPanel.tsx` · `resolveConfirmation` | 确认交互 | `interrupt` 的恢复 | 第5章 LangGraph·人工确认 | 第二次请求带回的是「答复」而非新输入，后端以 `Command(resume=…)` 从暂停点原地继续，已完成的节点不重跑、不重复调用模型 |
| `frontend/src/components/ConfirmationCard.tsx` | 确认交互 | 闸门期间无中间态 | 第5章 LangGraph·人工确认 | 暂停期间数据库干净，卡片展示的是草稿；没有「写进去再回滚」这一步，UI 也就不能承诺撤销 |
| `frontend/src/lib/api.ts` · `toTurns` | 会话回放 | 中断状态的持久化 | 第5章 LangGraph·人工确认 | 待确认内容随消息落进 `meta`，刷新页面后卡片能原样放回——检查点存在后端，但「该问用户什么」必须能被前端重建 |

### 本阶段的验证点

- `tests/test_api.py::test_stream_chat_emits_incremental_tokens` —— 追加断言 `tool_call`
  帧存在且 `agent == "tutor"`，即调用链的结构化来源确实在流里。
- `cd frontend && npm run typecheck && npm run build` —— 契约类型全量对齐后仍能通过
  （`intent` 删除后若有残留引用，`tsc` 会立刻报错）。
- 前端无自动化测试，端到端验收仍是 `curl -N /api/chat/stream` 看帧序列 +
  浏览器里确认卡片能正常落库。

### 一处契约收尾（记录原因）

**`intent` / `confidence` 两个字段彻底删除。** 计划把它列在前端待办里，实际是两端一起删：

- `confidence` 从来没有任何代码写过它，恒定 `0.0` —— 是一个必然误导人的字段；
- `intent` 取的是首个工具的智能体标识，与 `tool_calls[0].agent` 恒等，
  前端 `ToolChain` 已经在渲染同一件事，是同一事实的第二处来源；
- `chat_agent.py` 里的注释早就写着「前端改用 `tool_calls` 后删除」，本阶段正是那一刻。

受影响的用例 `test_api.py::test_chat_routes_intent_and_keeps_conversation` 改为断言
`tool_calls[0]["agent"] == "tutor"` —— 测的还是「路由到答疑讲师」这件事，只是换了权威来源。

## 按章节反查代码

文档落库后按章节复习时，从这里进入比按文件翻更快。

| 章节 | 涉及文件 |
| --- | --- |
| 第2章 LangChain 核心组件 | `app/schemas/subagent.py`、`app/llm/tasks.py`、`app/llm/factory.py`、`app/llm/structured.py`、`app/prompts/templates.py`、`app/prompts/context.py`、`app/workflows/chat_agent.py`、`app/schemas/workflow.py`、`app/agents/nudge.py`、`tests/fakes.py` |
| 第3章 Agent 进阶 | `app/workflows/chat_agent.py`、`app/workflows/state.py`、`app/services/conversations.py`、`app/prompts/context.py`、`app/agents/tools.py` |
| 第4章 RAG Agent | `app/knowledge/*` |
| 第5章 LangGraph | `app/workflows/state.py`、`graph.py`、`nodes.py`、`runner.py`、`chat_agent.py`、`checkpoint.py`、`app/services/conversations.py`、`frontend/src/lib/sse.ts`、`frontend/src/components/ChatPanel.tsx`、`frontend/src/components/ConfirmationCard.tsx` |

## 逐章复习顺序（建议）

按依赖关系读比按章节号读更顺：先看**状态怎么定义**（第5章·基本概念 → `state.py`），
再看**图怎么装**（第5章·基本概念 → `graph.py`、`nodes.py`），然后看**增量怎么流出来**
（第5章·流式 → `runner.py`、`chat_agent.py`、前端 `sse.ts`），最后看**怎么暂停与恢复**
（第5章·人工确认 → `checkpoint.py`、`confirm_plan`、前端确认卡片）。第2、3、4 章的内容
散布在这条主线的各节点内部，遇到时回溯即可。
按同样节奏追加，不攒到最后一次性补。