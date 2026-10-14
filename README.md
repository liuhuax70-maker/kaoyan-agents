# 基于智能体的考研考证学习规划与督促系统

面向考研与考证学生，利用大模型多智能体技术搭建**学习规划与督促系统**：根据用户基础、目标与备考时长自动生成个性化学习计划，完成任务拆解、进度跟踪与提醒督促。

## 核心能力

| 能力 | 说明 | 对应选题要求 |
| --- | --- | --- |
| 个性化计划生成 | 依据基础水平、目标院校/证书、剩余备考时长生成分阶段计划 | 自动生成学习计划 |
| 任务拆解 | 阶段目标 → 周任务 → 可打卡的最小学习单元 | 任务拆解 |
| 进度跟踪 | 任务打卡、完成度统计、阶段体检 | 进度跟踪 |
| 提醒督促 | 定时巡检、逾期催办、每日日报与周报复盘 | 提醒督促 |
| 提示词体系 | 各智能体独立 system prompt + 结构化输出约束 | **智能体提示词设计** |
| 工作流编排 | LangGraph 单一编排层；聊天 Agent 以 Subagents 模式调度 7 个子智能体工具，自身回答即最终回答 | **任务工作流编排** |
| 学习数据管理 | 用户、目标、科目、计划、任务、进度、提醒的完整建模 | **用户学习数据管理** |

## 多智能体架构（Subagents 模式）

用户只与**聊天 Agent** 对话。各板块的能力以「工具」形式暴露，调用哪些、按什么顺序、各调用几次，全部由聊天 Agent 自己决定；它的回答就是最终回答，不再有第二次总结。

### 编排拓扑

图由 `backend/app/workflows/graph.py` 编译，5 个节点、1 处条件边：

```
START
 └─▶ prepare_context     载入考生画像 / 当前计划 / 会话历史
      └─▶ chat_agent      工具调用循环；最终回答逐 token 流出
            ├─(有 plan_draft 且开启评审)─▶ review_plan
            └────────────────────────────▶ confirm_plan
                                            └─▶ finalize ─▶ END
```

- **子智能体**（`backend/app/agents/tools.py` 是唯一事实来源，新增只需登记一条）：

  | 工具 | 子智能体 | 说明 |
  | --- | --- | --- |
  | `generate_plan` | 备考规划师 | 生成分阶段计划 |
  | `breakdown_tasks` | 任务拆解师 | 阶段目标 → 可打卡任务 |
  | `explain_concept` | 答疑讲师 | 含知识库检索 |
  | `review_progress` | 复盘诊断师 | 进度体检与风险 |
  | `recommend_resources` | 资料规划师 | 资料与资源建议 |
  | `send_nudge` | 督学教练 | 督促提醒 |
  | `revise_plan` | 计划修订师 | 产出计划修订提案 |

- **双轨输出**：每个子智能体回灌给聊天 Agent 的是 `SubagentReply[T]` —— `narrative`（完整 markdown 正文）+ `data`（结构化产物）。正文直接进模型上下文，因此解题步骤与易错点原文能到达用户；结构化产物驱动落库与卡片渲染。
- **评审**：`review_plan` 节点复用 `PlanReviewResult` 与 `REVIEWER_ROLE`，由条件边触发，已从 CrewAI 迁为图节点。
- **图谱保持无副作用**：子智能体只产出结构化结果，落库由服务层在图执行完成后统一处理，因此工作流可以脱离数据库单测。

### 三项产品能力

| 能力 | 实现位置 | 说明 |
| --- | --- | --- |
| 多轮记忆 | `workflows/chat_agent.py` · `_history_messages` | 服务层从 `agent_messages` 取出被裁剪的历史，以真实 `HumanMessage`/`AIMessage` 序列插入 system 之后；图本身不读数据库 |
| 真·token 流式 | `workflows/runner.py` · `stream_workflow` | `astream(stream_mode=["custom","values"])`：`custom` 收聊天 Agent 逐字推出的 `token`，`values` 收 `outputs` / `events` / `tool_call` 增量 |
| 落库前人工确认 | `workflows/graph.py` · `confirm_plan` | 存在 `plan_draft` / `plan_revision` 时调用 `interrupt()` 暂停，**一个字都不写库**；`POST /api/chat/confirm` 以 `Command(resume=...)` 从原处恢复 |

确认能力与检查点同开关：挂载 checkpointer 才有暂停与恢复（`workflows/checkpoint.py`，开发用 SQLite、生产用 PostgreSQL）。`thread_id` 是**一轮对话一条线程**（`"{conversation_id}:{message_id}"`）而非一个会话一条 —— 线程状态是累加的，复用会话 ID 会把上一轮的产出与待确认计划续到这一轮。原因详见 [docs/code-knowledge-map.md](docs/code-knowledge-map.md) 阶段 4 的偏差记录。

### SSE 事件

| 事件 | 载荷 | 时机 |
| --- | --- | --- |
| `start` | `conversation_id` | 会话就绪 |
| `progress` | `node` / `status` / `detail` | 节点或子智能体开始执行 |
| `tool_call` | `name` / `agent` / `label` | 聊天 Agent 调起某个子智能体工具（调用链的权威来源） |
| `output` | `output: AgentOutput` | 子智能体产出结构化结果 |
| `token` | `text` | 最终回答的逐字增量 |
| `done` | `reply` / `agents` / `tool_calls` / `plan_id` / … | 本次执行完成 |
| `awaiting_confirmation` | `reply` / `confirmation` / … | 停在确认闸门上，**不会再有 `done`** |
| `error` | `message` | 失败收尾 |

### 计划表的两条修改路径

| 入口 | 链路 | 示例 |
| --- | --- | --- |
| 对话 | 聊天 Agent → `revise_plan` 工具 → 计划修订师产出修订提案 → 服务层落库 | 「把没做完的任务往后挪三天」 |
| 直接编辑 | `/plan` 页任务看板 | 改标题、改日期与时长、增删任务、改计划目标 |

两条路径共用 `backend/app/services/plan_edit.py` 的同一套底层函数，行为一致。

## 技术栈

- **智能体**：LangGraph（唯一编排层，Subagents 模式）+ LangChain（仅用 `langchain-openai` 做模型适配）
- **后端**：FastAPI + SQLAlchemy(async) + Alembic
- **存储**：PostgreSQL（业务数据）+ Redis（缓存/消息队列）+ Milvus（向量检索）
- **异步任务**：Celery + Redis Beat（定时督促）
- **大模型**：DeepSeek（默认）+ Ollama（本地备选），统一走 OpenAI 兼容适配层
- **前端**：Next.js（React）+ react-markdown（助手正文为 markdown，需真实解析）
- **可观测性**：LangFuse
- **部署**：Docker / Docker Compose

## 目录结构

```
kaoyan-agents/
├── docker-compose.yml          # 基础设施 + 应用编排
├── .env.example                # 环境变量模板
├── backend/
│   ├── app/
│   │   ├── core/               # 配置、日志、异常
│   │   ├── db/                 # 数据库引擎、会话、模型
│   │   ├── cache/              # Redis 客户端
│   │   ├── schemas/            # 智能体输入快照与结构化输出
│   │   ├── prompts/            # 智能体提示词与角色定义
│   │   ├── llm/                # 模型工厂与结构化输出解析
│   │   ├── agents/             # 子智能体工具注册表
│   │   ├── workflows/          # LangGraph 编排（5 节点图 + 工具循环 + 检查点）
│   │   ├── knowledge/          # 向量库与 RAG 检索
│   │   ├── tasks/              # Celery 定时任务
│   │   └── api/                # FastAPI 路由
│   ├── alembic/                # 数据库迁移
│   ├── scripts/                # 基础设施自检与端到端冒烟脚本
│   └── tests/                  # fakes.py 提供假模型 / 假向量化 / 内存检查点
├── docs/                       # 设计与参照文档，见下方「文档」
└── frontend/                   # Next.js 工作台
    ├── src/app/                # 多智能体对话 / 学习计划
    ├── src/components/         # 面板、markdown 正文、确认卡片与基础 UI
    └── src/lib/                # 接口封装、SSE 解析与类型定义
```

## 快速开始

### 1. 启动基础设施（需要 Docker Desktop 已运行）

```bash
docker compose up -d
```

启动 PostgreSQL(5432)、Redis(6379)、Milvus(19530)、etcd、MinIO(9000/9001)。

### 2. 启动后端

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
cp ../.env.example ../.env      # 按需修改
uvicorn app.main:app --reload --port 8000
```

接口文档：http://localhost:8000/docs
健康检查：http://localhost:8000/api/health

### 3. 无 Docker 的本地开发

配置体系内置兜底，可在没有 Docker 的情况下跑通数据库、缓存与测试：

- `DATABASE__URL=sqlite+aiosqlite:///./data/kaoyan.db`
- `VECTOR__BACKEND=local`（本地向量兜底实现，不依赖 Milvus）
- `CELERY__TASK_ALWAYS_EAGER=true`
- `EMBEDDING__PROVIDER=ollama`（本地真实语义检索；无 Ollama 时检索自动降级为空结果）
- `LLM__DEFAULT_PROVIDER=ollama`（本地模型；测试用 `tests/fakes.py` 的假模型，不依赖密钥）

### 4. 启动前端工作台

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

前端通过 `NEXT_PUBLIC_API_BASE` 直连后端（默认 `http://localhost:8000`）。后端已放行
`localhost:3000` 跨域，因此不做反向代理 —— SSE 流式响应不会被中间层缓冲。

| 页面 | 路径 | 内容 |
| --- | --- | --- |
| 多智能体对话 | `/chat` | SSE 流式协作过程、智能体回答、历史会话（根路径 `/` 重定向到此） |
| 学习计划 | `/plan` | 任务看板与打卡、备考目标与档案编辑、提醒督促 |

首次进入输入任意用户名即可：已存在则直接登录，不存在则自动注册一个带默认档案的账号。

### 5. 启动定时任务（提醒督促）

```bash
cd backend
# 执行队列
celery -A app.tasks.celery_app:celery_app worker -l info
# 定时调度
celery -A app.tasks.celery_app:celery_app beat -l info
```

本地开发可设 `CELERY__TASK_ALWAYS_EAGER=true`，任务会在调用处直接同步执行，无需 Redis。

### 6. 一键启动全部容器

```bash
docker compose --profile app up -d
```

包含 frontend、backend、worker、beat 四个应用容器与全部基础设施。

首次构建需拉取 Python 与 Node 依赖，直连官方源会因速度过慢而超时。可临时指定国内镜像：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
NPM_REGISTRY=https://registry.npmmirror.com \
docker compose --profile app build
```

（也可以写进 `.env`，compose 会自动读取；这两个变量只在构建期生效。）

### 7. 接入 LangFuse 可观测性（可选）

未配置密钥时全部埋点都是空操作，不影响任何功能。

**方式一：LangFuse Cloud（推荐，开发阶段零运维）**

```env
OBSERVABILITY__LANGFUSE_ENABLED=true
OBSERVABILITY__LANGFUSE_PUBLIC_KEY=pk-lf-...
OBSERVABILITY__LANGFUSE_SECRET_KEY=sk-lf-...
OBSERVABILITY__LANGFUSE_HOST=https://cloud.langfuse.com
```

**方式二：自托管**

```bash
docker compose -f docker-compose.observability.yml up -d
```

需要 PostgreSQL + ClickHouse + Redis + MinIO 四个组件，建议至少 4GB 内存。

接入后每一次多智能体协作都会生成一条 trace，其中包含：意图、参与智能体、
命中的科目与剩余天数、最终回复；每次模型调用生成一个 generation，
记录模型名、耗时与 token 用量。trace 链接会随对话一起存入 `agent_messages.meta`。

### 8. 部署自检

容器就绪后，用两个脚本确认交付链路完整（均在 `backend/` 目录下执行）：

```bash
python -m scripts.verify_infrastructure   # 依赖连通性：PostgreSQL / Redis / 向量库写入+检索往返
python -m scripts.smoke_api               # 端到端：建账号 → 定目标 → 生成计划 → 对话 → 打卡 → 提醒 → 检索
```

`verify_infrastructure` 只做只读探测，可随时重复执行；`smoke_api` 每次会新建一个 `smoke_*` 测试考生。

### 9. 国内网络加速

PyPI 直连较慢时，pip 会因拉取索引超时而报 `Could not find a version ... (from versions: none)`，改用国内镜像即可：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
npm config set registry https://registry.npmmirror.com
```

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/users` | 创建用户（可同时初始化学习档案） |
| GET | `/api/users/lookup?username=` | 按用户名找回账号（前端登录用） |
| GET | `/api/users/{id}` | 查询用户与档案 |
| PATCH | `/api/users/{id}` | 更新用户与学习档案 |
| POST | `/api/targets` | 创建备考目标与科目 |
| GET | `/api/targets?user_id=` | 目标列表 |
| GET | `/api/targets/{id}` | 目标详情 |
| POST | `/api/plans/generate` | 触发工作流生成计划并落库 |
| GET | `/api/plans?user_id=` | 计划列表（含阶段与任务） |
| GET | `/api/plans/{id}` | 计划详情 |
| GET | `/api/tasks?user_id=&status=` | 任务列表 |
| PATCH | `/api/tasks/{id}` | 任务打卡与调整 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| GET | `/api/tasks/{id}/progress` | 打卡历史 |
| PATCH | `/api/plans/{id}` | 修改计划标题 / 目标 / 策略 |
| POST | `/api/plans/{id}/tasks` | 新增任务（用户直接编辑计划表） |
| POST | `/api/chat` | 多智能体对话 |
| POST | `/api/chat/stream` | 多智能体对话（SSE 流式） |
| POST | `/api/chat/confirm` | 确认或驳回待落库的计划（`interrupt` 恢复） |
| GET | `/api/chat/conversations?user_id=` | 会话列表与详情 |
| GET | `/api/reminders?user_id=` | 提醒记录 |
| POST | `/api/reminders/run?kind=` | 手动触发一轮提醒（联调与演示） |
| GET | `/api/knowledge/stats` | 知识库状态 |
| POST | `/api/knowledge/ingest` | 写入内置语料 |
| POST | `/api/knowledge/search` | 语义检索 |
| GET | `/api/overview` | 系统能力总览（角色 / 提示词 / 工作流 / 定时计划） |
| GET | `/api/dashboard?user_id=` | 工作台概览（进度 / 计划 / 提醒） |
| GET | `/api/health` | 健康检查 |

交互式文档：http://localhost:8000/docs

## 文档

| 文档 | 内容 | 什么时候看 |
| --- | --- | --- |
| [docs/backend-refactor-plan.md](docs/backend-refactor-plan.md) | Subagents 架构收敛的根因诊断、目标架构、分阶段方案与风险表 | 想了解「为什么是现在这个形状」 |
| [docs/code-knowledge-map.md](docs/code-knowledge-map.md) | 代码 ↔ 知识点的全量对照表，附按课程章节反查代码的索引 | 复习知识点、面试答辩时定位实现 |

源码里每个函数/类上方都有一到两行 `# 知识点：…（第X章 …）` 标注，格式与取用规则见
[code-knowledge-map.md 的开头](docs/code-knowledge-map.md)。对照表按重构阶段分节，
前五节对应阶段 0–4。

## 开发节点

| 节点 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 工程骨架、配置体系、Docker 编排、健康检查 | 已完成 |
| 2 | 学习数据模型与 Alembic 迁移 | 已完成 |
| 3 | 智能体提示词体系与结构化输出 | 已完成 |
| 4 | LangGraph 任务工作流编排 | 已完成 |
| 5 | 计划评审（已从 CrewAI 迁为 LangGraph 图节点） | 已完成 |
| 6 | Milvus 向量库与 RAG 检索 | 已完成 |
| 7 | Celery 提醒督促定时任务 | 已完成 |
| 8 | FastAPI 业务接口层（含 SSE 流式） | 已完成 |
| 9 | LangFuse 可观测性接入 | 已完成 |
| 10 | Next.js 前端工作台 | 已完成 |
| 11 | 测试、镜像与部署文档 | 已完成 |
| 12 | 架构收敛重构（Subagents v2）：单一编排层、双轨输出、多轮记忆、token 流式、计划确认 | 已完成 |
