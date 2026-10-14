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

## 阶段 6：择校情报底座（联网搜索 + 官方入口兜底）

产品规格要求择校能力给出**多所院校**与**可核验的链接**，而此前全仓没有任何联网能力：
唯一的出站 HTTP 是 embeddings 客户端，界面上那个「联网搜索」开关实际开的是知识库检索。
本阶段只建情报底座 —— 不含 LLM、不含新表、不含新智能体，可独立验证。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `search/types.py` · `SearchResult.to_chunk` | 多数据源接入 | 统一片段形状 | 第4章 RAG Agent·构建知识库 | 新数据源只要产出同一种「带来源的片段」，引用渲染与溯源链路就不必重写；`source` 取页面标题（给人读），URL 另放 `metadata`（给前端做链接），两者不能混为一谈 |
| `search/official_links.py` · `official_entry_links` | 幻觉抑制 | 把「去哪核验」从模型手里拿走 | 第4章 RAG Agent | 让模型写院校域名等于请它编造链接，而编错的链接就是「把假事实当事实交付」；只给确定性入口与搜索跳转 URL，最坏情况也只是「多跳一次搜索」而不是「指向抢注域名」 |
| `search/base.py` · `gather_school_intel` | 降级契约 | 增强能力失败不得中断主链路 | 第4章 RAG Agent·构建知识库 | 与 `retrieve_context` 同一条契约：未启用/无密钥/超时/报错一律降级而非抛出；且降级内容本身要有用 —— 官方入口不依赖任何外部服务，所以「没搜到」不等于「什么都没给」 |
| `prompts/context.py` · `render_web_intel` | 引用与溯源 | 片段必须连同来源一起进提示词 | 第4章 RAG Agent | 无来源的片段只能被当成通用知识复述，带上 URL 才可能被引用成可核验线索；另外「未启用」与「搜了没结果」对模型的约束不同，必须分开说明 |
| `core/config.py` · `SearchSection` | 配置 | 提供方差异集中在配置 | 第2章 LangChain 核心组件 | 与 `EmbeddingSection` 同形：Tavily 与博查协议不同但职责相同，差异归一为 `api_key`/`base_url` 两个属性，调用方拿到的结果与用的是哪家无关 |

### 本阶段的验证点

- `tests/test_search.py` —— 16 个用例分三层：客户端断言「构造出什么请求 + 怎么解析响应」
  （含相关性字段是字符串或 `null` 时的兜底），门面断言「未启用 / 无密钥 / HTTP 500 三条
  降级路径」，官方入口断言**主机名白名单**（`yz.chsi.com.cn` 或 `www.baidu.com` 之内，
  而不是断言某条具体链接长什么样 —— 后者一改模板就红，前者才守住「不编造域名」这条不变量）。
- `tests/test_health.py` —— 健康检查新增 `search` 组件。默认为「未就绪」是预期状态而非故障，
  但必须可见，否则线上排查「择校情报为什么是空的」会无从下手。
- 未引入任何新依赖：只用已装的 `httpx`。少一个依赖就少一处需要跟着协议变更维护的地方。

### 一处刻意的分层（记录原因）

**客户端不吞异常，降级只发生在门面。** `TavilySearchClient.search` 遇到 HTTP 500 直接
`raise_for_status` 抛出去，由 `gather_school_intel` 兜住。这样两个契约可以分别测试：
「HTTP 失败要抛出」和「失败后要降级」是两件事，混在一个函数里就只能一起测。
测试假件也按同样原则——`install_fake_search` 只替换客户端的 `search` 方法，
**不替换 `build_search_client` 工厂**，因此「无密钥应报 `ConfigurationError`」这条契约在测试中依然成立。

## 阶段 7：择校智能体 + 候选院校持久化

产品规格里最硬的一条是「不能帮用户做决定，只能听取用户的唯一决定」。这句话不能靠
提示词里写一句「请不要排名」来落实 —— 提示词是散文，无法验证。本阶段把这条约束
**翻译成四层结构**，并让「谁做的决定」在数据上可区分：参谋只被允许写 `candidate` 行，
把某一行提升为 `decided` 并写回 `ExamTarget.target_school` 的只有用户的显式动作。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `schemas/school.py` · `_FORBID_EXTRA` | 结构约束 | 结构化输出的封闭契约 | 第2章 LangChain核心组件·结构化输出 | 只有 `extra="forbid"` 才会让 `model_json_schema()` 输出 `additionalProperties: false`，而提示词渲染只剥字符串型的 `title` —— 于是「不许出现的字段」是被模型看得见的契约，多吐一个键就是可拦截的校验错误 |
| `schemas/school.py` · `_candidates_must_be_distinct` | 结构约束 | 跨字段规则不在 Schema 里 | 第2章 LangChain核心组件·结构化输出 | `mode="after"` 的校验器不进 JSON Schema，模型**看不到**它；这类规则必须在角色提示词里复述一遍，否则模型只能在重试时才知道自己错了（烧掉重试预算） |
| `schemas/school.py` · `candidates` 的长度约束 | 结构约束 | 用 Schema 表达业务不变式 | 第2章 LangChain核心组件·结构化输出 | 「至少三所」写成 `Field(min_length=3)` 后落进契约的 `minItems`，模型一开始就知道底线；能靠 Schema 表达的约束不要写进校验器，那是兜底而不是说明 |
| `prompts/catalog.py` · `SCHOOL_ADVISOR_ROLE.extra_rules` | 提示词 | 不可信输入的边界 | 第4章 RAG Agent | 联网片段来自互联网、可能过期或有误，只能当线索：提示词必须写明「不得把片段里的分数线/报录比当事实复述」，并给出核验入口 —— 提供线索、不做权威背书 |
| `workflows/nodes.py` · `_run_school_advisor` | 降级 | 增强能力的降级不中断主链路 | 第4章 RAG Agent·构建知识库 | 联网与知识库都是「有则更好」：两者各自降级、各自渲染，任一不可用时择校仍能给出候选与核验入口（官方入口不依赖任何外部服务） |
| `workflows/nodes.py` · `_run_school_advisor` | 检索 | 逐次查询的片段不进向量库 | 第4章 RAG Agent·构建知识库 | 向量库是**持久**知识（这里是 9 篇方法论语料），逐次查询的易失片段写进去等于污染语料，还得再做过期删除；这个基数上做 embed + 余弦 + top_k 只会丢掉本来有用的那条 |
| `agents/tools.py` · `advise_schools` | 架构 | Subagents 的可扩展点 | 第3章 Agent进阶·Multi Agent | 新增一个子智能体 = 一个工具 + 一个处理器，聊天 Agent 的分派逻辑一行不改；`test_every_tool_maps_to_a_real_subagent` 断言工具数与处理器数相等，两边不可能各走各的 |
| `workflows/chat_agent.py` · `_merge` | 状态 | 新产物字段的传播清单 | 第5章 LangGraph·基本概念 | 处理器返回的状态片段要合并进最终状态，白名单式的传播元组漏一项，产物就永远到不了 API —— `WorkflowResult.digest` 这个死字段就是「只声明字段什么都不接」的活标本 |
| `frontend/src/components/AgentAnswer.tsx` · `referenceUrl` | 引用与溯源 | 引用来源的可点形态 | 第4章 RAG Agent·构建知识库 | 片段统一带 `metadata.url`，语料片段没有该键 —— 于是同一块引用 UI 能同时服务两类来源：有 URL 的渲染成链接，没有的退回纯文本 |

### 本阶段的验证点

- `tests/test_school.py` —— 18 个用例分三层。Schema 层逐条验证「不替用户决定」的结构防线：
  排序/推荐字段被拒、少于三所被拒、缺优劣势被拒、重名与 `fit_for` 雷同被拒。
  工作流层验证工具路由、核验入口注入且**主机名只在白名单内**、联网片段进引用列表。
  服务层验证候选重复落库幂等且保留已拍板状态、`decide_school` 是唯一写回路径、
  跨目标的 `school_id` 被拒、归档是状态迁移而非删除。
- `test_output_contract_declares_additional_properties_false` —— 守的是**机制**而不是行为：
  它断言契约文本里确实有 `additionalProperties: false`。将来若有人改 `_strip_titles`
  的行为，这条会先红 —— 否则「禁止排序字段」会静默退化成一句无人执行的散文。
- `test_role_restates_invariants_not_visible_in_schema` —— 反向守住第三层：
  校验器里的跨字段规则必须同时出现在 `extra_rules` 里，模型才看得见。
- `test_candidates_stay_candidate_when_persisted` —— 走完整的
  `run_workflow` → `persist_result` 回环，断言 `ExamTarget.target_school` 仍是空串。
  「产品没替用户做决定」这条声明，就是靠这个断言变成可验证的事实的。
- `tests/test_migrations.py` —— `EXPECTED_TABLES` 加 `tracked_schools` 后，
  全新 SQLite 升级 + 完整回滚到 base 仍然通过。

### 一处刻意的分层（记录原因）

**把「不替用户决定」拆成四层，各管一段，而不是靠提示词一句禁令。**

1. **字段根本不存在** —— `extra="forbid"`，且规则在模型看到的契约文本里可见（见上表）。
2. **解析期的长度约束** —— `candidates` 至少三所、每所 `pros`/`cons` 各至少一条。
3. **跨字段机械不变式** —— 只查「名称不重复」与「适用人群描述不雷同」，因为这是
   「多个候选」塌缩成「同一个答案反复说」的**唯一两种机械方式**。**刻意不查**任何
   「是不是有某所悄悄最优」的启发式：那类规则会在合法输出上误报，把重试预算烧光，
   最后落到 `StructuredOutputError` —— 反而比不查更糟。
4. **`narrative` 是自由文本，结构管不了** —— 只能靠散文，因此 `extra_rules` 里必须
   写明不得排名、不得标注推荐、并原文承接规格那句「让决定权落在用户身上，
   我们不能帮用户做抉择，这是一件人生大事」。

**`services/targets.py` 整体不加知识点标注。** 该文件是纯粹的持久化与状态迁移
（幂等 upsert、单 DECIDED 不变式、归档不删除），课程里没有与之对应的知识点，
按「对不上就不标」处理。它的存在理由写在模块文档字符串里：没有这层分离，
「产品没有替用户做决定」就只是一句无法验证的声明。

### 一处更正：那个名不副实的「联网搜索」开关（记录原因）

真实搜索落地之前，聊天输入框旁的地球图标写着「联网搜索」，绑的却是 `enable_retrieval`
（本地知识库检索）—— 它从来没有搜过任何东西。当时这是个无害的措辞问题，**真搜索落地后
它就承重了**：用户打开「联网搜索」期待的是院校情报，拿到的却是本地语料，而真正的联网
能力反而没有入口。本阶段把它拆开：

- 原地球图标改名为 **「知识库检索」**（默认开），绑定 `enable_retrieval` 不变；
- 新增 **「联网搜索」**（默认关），经 `ChatRequest.enable_search` →
  `WorkflowState.enable_search` → `_should_search` 落到择校情报上。

默认值一开一关是刻意的：`_should_search` 与 `_should_retrieve` **各查各的配置段**，
知识库默认可开（本地语料），联网默认关闭（需要密钥）。把两者绑在一个开关上，
默认值就会互相打架 —— 这正是 `_should_search` 的文档字符串里写明的那条理由。

**`TrackedSchool` 是全新实体，因此绕开了 SQLite 改 CHECK 的麻烦。** `enum_column`
落在既有的 `ReminderType` 上时留了具名 CHECK，加成员必须重建表（阶段 8 的活）；
而新实体自声明约束名，直接建新 CHECK 即可。这条分层是刻意的：**除非必要，
不给既有枚举加成员**。

## 阶段 8：每日院校简报 + 断签放宽

验收标准 2 要求「**每天**返回目标考研院校目标专业的情况，且**给出链接**让用户确认
真实情况」。本阶段把它落成第五类提醒 `school_brief`；同时把「断签预警」的触发口径
从「距上次学习多少天」换成「连续多少天零投入」—— 前者是展示口径，拿它当触发条件
会把手握低自律度用户的提醒写成催办。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `agents/school.py` · `compose_school_brief` | 结构化输出 | 双轨信封只对 `SUBAGENT_TASKS` 生效 | 第2章 LangChain 核心组件·结构化输出 | 简报只有 Celery 路径消费、只要结构化数据，因此走 `invoke_agent_task`（输出模型就是 `SchoolBrief` 本体），与 `compose_weekly_digest` 同形 |
| `agents/school.py` · `format_brief_content` | 幻觉抑制 | 可核验链接不交给模型生成 | 第4章 RAG Agent | 核验入口由系统按确定性规则拼成 markdown，模型只能给文字建议；「每天给链接」这条验收因此不取决于模型是否听话 |
| `services/reminders.py` · `_create_school_brief_reminder` | 降级契约 | 增强能力失败不中断主链路 | 第4章 RAG Agent·构建知识库 | 联网情报失败时照常投递，因为核验入口由 `official_entry_links` 保证在场 —— 「没搜到」不等于「没简报」 |
| `services/snapshots.py` · `consecutive_zero_days` | 督促触发口径 | 触发用「连续零投入」而非「距上次学习天数」；且不打扰还没起步的用户 | 第3章 Agent 进阶 | 自律度低的用户隔三差五不打卡是常态，只看展示口径会写成催办；新口径要求窗口内每一天都没有 `actual_minutes > 0` 的打卡，而 `StudyStreak` 缺失或 `last_study_date` 为空时一律返回 0（不预警） |
| `frontend/src/components/ReminderPanel.tsx`、`Markdown.tsx` | 引用与溯源 | 链接必须真的可点 | 第4章 RAG Agent | 站内信此前是纯文本渲染，简报里的核验入口会退化成死文本；改走 `Markdown` 并给外链加 `target="_blank"`，「给出链接」这条验收才在界面上成立 |

### 本阶段的验证点

- `tests/test_tasks.py::test_school_brief_task_generates_and_delivers` —— eager 链路走完
  「找跟踪院校 → 生成 → 落库 → 投递」，断言提醒类型为 `SCHOOL_BRIEF`、内容里含 markdown
  链接语法（`](http`）。
- `tests/test_tasks.py::test_school_brief_falls_back_to_official_links_when_search_degraded`
  —— 默认搜索关着，简报照投，且研招网入口必须在场。
- `tests/test_services.py` 三个断签用例 —— 分别钉住「两天前有打卡、但上次学习记录停在 5 天前
  → 只算 2 天（旧的展示口径会误报 5 ≥ 3）」、尾部连续 3 天零投入 → 返回 3、无 `StudyStreak`
  → 返回 0。
- `tests/test_migrations.py` —— 全新 SQLite 升级 + 完整回滚到 base 仍然通过，兜住本阶段
  唯一带破坏性的迁移。
- `tests/test_api.py::test_overview_exposes_roles_and_workflow` —— `/api/overview` 的
  `schedule` 从四项变五项，用例改成断言集合相等，漏登记 beat 条目会立刻红。

### 一处刻意的取舍（记录原因）

**断签阈值新增 `idle_zero_days`，而不挪用既有的 `idle_threshold_days`。** 两者口径不同：
`idle_threshold_days` 是**展示**口径（`render_learner` 打印「连续未学习 N 天」，且被既有
测试引用），`idle_zero_days` 是**触发**口径（连续零投入天数）。共用一个字段会让「给用户看的
数字」与「决定要不要打扰他的阈值」悄悄耦合 —— 改其中一个会莫名其妙地动到另一个。

**`consecutive_zero_days` 的窗口锚在调用方传入的 `today`，而不是「此刻」。** 否则调用方
传固定日期做确定性测试时，窗口起点会漂到真实时间的今天去，用例会随运行日期时红时绿。

**「两天前有打卡但上次学习记录在 5 天前」这个用例是刻意构造的。** 它正好落在新旧口径
分叉的那条缝上：旧口径读 `idle_days = 5 ≥ 3` 会误报，新口径读打卡只算 2 天、不打扰。
没有这个用例，改口径这件事在测试里就是不可见的。

**给既有枚举加成员是唯一带破坏性的迁移，因此「除非必要不加成员」升级为一条纪律。**
`TrackedSchool`（阶段 7）是全新实体，自声明约束名即可直接建新 CHECK；而
`ReminderType.SCHOOL_BRIEF` 落在既有列上，必须 `batch_alter_table(recreate="always")`
重建整张 `reminders` 表 —— 这也是本次三处迁移里唯一需要在 downgrade 里先
`DELETE` 存量新成员行的原因：枚举收窄后它们过不了新表的 CHECK，拷贝数据那一步会整条
失败，而不是「少几行」。

**迁移里的枚举 CHECK 重建不加知识点标注。** `batch_alter_table` 是 SQLite 的存储机制，
课程里没有与之对应的知识点；理由写在迁移文件自身的模块文档字符串里。判据同阶段 7 的
`services/targets.py`：**对不上就不标**。

**Celery beat 的错峰（`school-brief` 取 `:15`）同样不标知识点。** 它是调度工程而非
LangChain/LangGraph 概念，理由留在 `celery_app.py` 的普通注释里，不占对照表的一行。

## 阶段 9：课表化计划（时段 + 周视图 + 今日目标）

验收标准 3 要求计划像**课程表**那样列出来，并在最右侧的小格子里列出**今日要达成的
目标**。此前的 `StudyTask` 只有 `planned_date` + `order_index`，没有任何时段概念 ——
「第几天」有了，「那天的哪一段」没有。本阶段补上时段维度：模型可以在草稿里指定，
留空的由确定性代码按用户偏好补齐，界面上呈现为「周一~周日 × 上午/下午/晚上」的网格。

| 代码位置 | 板块 | 知识点 | 文档定位 | 一句话原理 |
| --- | --- | --- | --- | --- |
| `services/scheduling.py` · `order_tasks` / `slot_rank` | 排序口径 | 排序口径的单一来源 | 第3章 Agent 进阶·工具可靠性 | 中文字典序**不等于**时间顺序（`"上午" < "下午" < "晚上"` 不成立），裸的 `order_by(slot)` 是静默错的排序；把「谁在前」抽成一处映射供三个加载器复用，口径才不会各自漂移 |
| `services/scheduling.py` · `assign_slots` | 结构化输出 | 模型给不全的，由确定性代码补齐 | 第2章 LangChain 核心组件·结构化输出 | 与「模型不碰日期、只给 `day_offset`」同一条理路：时段这种可推导的字段让模型猜只会引入噪声，落库前按偏好做水线填充既确定又可单测 |
| `schemas/common.py` · `Slot`、`schemas/plan.py` · `TaskDraft.slot` | 结构化输出 | 取值约束写进契约而非散文 | 第2章 LangChain 核心组件·结构化输出 | `Literal` 会在 JSON Schema 里落成 `enum`，模型因此**看得见**它只能吐三个值；写进提示词散文则只是一种请求，无从校验 |

### 本阶段的验证点

- `tests/test_api.py::test_slot_ordering_uses_natural_slot_order` —— 三个任务按
  晚上/上午/下午 的顺序创建（`order_index` 依次 0/1/2），接口必须按 上午→下午→晚上
  返回。这是 `slot_rank()` 的回归测试：去掉它，返回的就是创建顺序。
- `tests/test_services.py` 三个分配用例 —— 偏好时段决定落在哪一行、模型已给时段的不覆盖、
  `attention_span` 作为水线高度（一个时段堆满才换行）、偏好为空时退回全部时段。
- `tests/test_services.py::test_persist_plan_draft_fills_missing_slots` —— 偏好只有
  「晚上」时每个任务都落在晚上，证明分配真的读到了档案。
- `tests/test_api.py::test_generate_plan_persists_plan_and_tasks` 增补两条断言：
  科目名与时段都要一路传到接口 —— 课表的「今日目标」按科目汇总，取不到名就只能全归「其他」。
- `tests/test_migrations.py` —— 加列迁移同样跑全新 SQLite 升级 + 完整回滚。

### 一处刻意的取舍（记录原因）

**`slot` 用可空 `String(8)`，不用新枚举。** `study_tasks` 是**既有表**，加枚举列意味着
加 CHECK，而 SQLite 改不了列约束、只能整表重建（对比阶段 8 那次 `reminders` 重建）。
时段只在课表里用于展示与排序、从不做筛选键，DB 层校验买不到任何东西；
取值约束上移到 Pydantic 的 `Slot`，权威词表放在 `services/scheduling.py` 的 `SLOTS`，
`schemas/common.py` 的 `Slot` 只是它的类型投影 —— 一套词表，一处定义。

**`StudyTask.subject` 的加载策略从 `lazy="raise"` 改成 `lazy="selectin"`。** 这是本阶段
唯一动了既有关系的地方，理由具体：课表的「今日目标」要按**科目名**汇总，而
`TaskRead` 此前只有 `subject_id`。`Subject` 没有指回 `StudyTask` 的反向集合，
`selectin` 不会形成循环预加载；而逐个端点铺 `selectinload(StudyTask.subject)` 要改六处
（列表、详情、打卡、新增、计划列表、计划详情），漏一处就是「有的任务有科目名、有的没有」
这种最难查的差异。`subject_name` 属性仍用 `inspect(...).unloaded` 兜底，未加载时返回空串
而不是触发懒加载（异步会话里懒加载会抛 `MissingGreenlet`）。

**`create_task` 改成直接挂 `Subject` 对象，而不是写 `subject_id`。** 顺带的收益是新建出来的
任务立刻就有科目名，接口不必为了一行响应再查一次；代价是 `plan_edit._subject_index`
（名称→主键的映射）失去了唯一调用方，已删除，替换为 `_find_subject`。

**`TaskRead.subject` 用 `validation_alias="subject_name"` 取值。** 字段名只能是 `subject`
（契约好看），但 ORM 上 `subject` 已是关系名，所以从 `subject_name` 属性读。已实测
Pydantic v2 的 `from_attributes` 会遵循 `validation_alias`，且序列化仍输出字段名
`subject`（`validation_alias` 不影响序列化）。

**课表挂在 `PlanBoard` 内部而不是 `page.tsx` 之上。** 计划原文写的是「挂在计划页
（`PlanBoard` 之上）」，但 `page.tsx` 手上没有任务列表 —— 挂在它那一层就要为了同一个
计划再发一次请求，两份数据还可能不同步。挂在 `PlanBoard` 返回内容的最上方，
视觉上同样是「看板之上」，且只有一份数据源。

**周次导航（上一周/本周/下一周）属于必要补充，不算「具体前端效果」的越界。**
一个 60 天的计划铺进固定的一周网格只看得见约七分之一的任务，没有翻页的课表是残缺的。
除此之外没有再加动效、拖拽这类效果 —— 那些按规格留到「届时再考虑」。

**「今日目标」的聚合口径放在纯函数 `lib/timetable.ts` 里，而不是散在组件内。**
验收标准把它写成一条可计算的规则（只看今天、只算未完成、空科目归「其他」、按时长降序），
放纯函数才能单测，也才能保证「当时算的」与「界面上看到的」不可能不一致。
`SLOTS` 同样是全前端唯一的时段定义处：网格、今日目标、表单下拉都从这里取词，
三处各写一份字符串是课表最常见的漂移来源。

**`buildGrid` 给没有时段的任务单独留一行「未定时段」，而不是塞进某一格。**
课表的价值就在位置说明安排，硬塞会让用户以为那是他计划好的时段；
留一行反而把「这些还没排」讲清楚了。

## 按章节反查代码

文档落库后按章节复习时，从这里进入比按文件翻更快。

| 章节 | 涉及文件 |
| --- | --- |
| 第2章 LangChain 核心组件 | `app/schemas/subagent.py`、`app/schemas/school.py`、`app/schemas/plan.py`、`app/schemas/common.py`、`app/llm/tasks.py`、`app/llm/factory.py`、`app/llm/structured.py`、`app/prompts/templates.py`、`app/prompts/context.py`、`app/workflows/chat_agent.py`、`app/schemas/workflow.py`、`app/agents/nudge.py`、`app/agents/school.py`、`app/services/scheduling.py`、`tests/fakes.py` |
| 第3章 Agent 进阶 | `app/workflows/chat_agent.py`、`app/workflows/state.py`、`app/services/conversations.py`、`app/prompts/context.py`、`app/agents/tools.py`、`app/services/snapshots.py`（`consecutive_zero_days`）、`app/services/scheduling.py`（`order_tasks`） |
| 第4章 RAG Agent | `app/knowledge/*`、`app/search/*`、`app/prompts/context.py`（`render_retrieved` / `render_web_intel`）、`app/prompts/catalog.py`（`SCHOOL_ADVISOR_ROLE`）、`app/workflows/nodes.py`（`_run_school_advisor`）、`app/agents/school.py`、`frontend/src/components/AgentAnswer.tsx`、`frontend/src/components/Markdown.tsx`、`frontend/src/components/ReminderPanel.tsx` |
| 第5章 LangGraph | `app/workflows/state.py`、`graph.py`、`nodes.py`、`runner.py`、`chat_agent.py`、`checkpoint.py`、`app/services/conversations.py`、`frontend/src/lib/sse.ts`、`frontend/src/components/ChatPanel.tsx`、`frontend/src/components/ConfirmationCard.tsx` |

> 阶段 7 的持久化与服务层（`app/db/models/target.py` 的 `TrackedSchool`、
> `app/services/targets.py`、`app/api/routes/targets.py`）**不在这张表里** ——
> 它们是纯粹的落库与状态迁移，没有可对上的知识点，理由见阶段 7 的「刻意的分层」。

## 逐章复习顺序（建议）

按依赖关系读比按章节号读更顺：先看**状态怎么定义**（第5章·基本概念 → `state.py`），
再看**图怎么装**（第5章·基本概念 → `graph.py`、`nodes.py`），然后看**增量怎么流出来**
（第5章·流式 → `runner.py`、`chat_agent.py`、前端 `sse.ts`），最后看**怎么暂停与恢复**
（第5章·人工确认 → `checkpoint.py`、`confirm_plan`、前端确认卡片）。第2、3、4 章的内容
散布在这条主线的各节点内部，遇到时回溯即可。
按同样节奏追加，不攒到最后一次性补。