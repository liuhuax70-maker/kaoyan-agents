# 基于智能体的考研考证学习规划与督促系统

以「选题 6」为背景，面向考研与考证学生，利用大模型多智能体技术搭建**学习规划与督促系统**：根据用户基础、目标与备考时长自动生成个性化学习计划，完成任务拆解、进度跟踪与提醒督促。

## 核心能力

| 能力 | 说明 | 对应选题要求 |
| --- | --- | --- |
| 个性化计划生成 | 依据基础水平、目标院校/证书、剩余备考时长生成分阶段计划 | 自动生成学习计划 |
| 任务拆解 | 阶段目标 → 周任务 → 可打卡的最小学习单元 | 任务拆解 |
| 进度跟踪 | 任务打卡、完成度统计、阶段体检 | 进度跟踪 |
| 提醒督促 | 定时巡检、逾期催办、每日日报与周报复盘 | 提醒督促 |
| 提示词体系 | 各智能体独立 system prompt + 结构化输出约束 | **智能体提示词设计** |
| 工作流编排 | LangGraph 状态机驱动多阶段编排 | **任务工作流编排** |
| 学习数据管理 | 用户、目标、科目、计划、任务、进度、提醒的完整建模 | **用户学习数据管理** |

## 技术栈

- **智能体**：LangGraph（工作流状态机编排）+ LangChain + CrewAI（角色分工）
- **后端**：FastAPI + SQLAlchemy(async) + Alembic
- **存储**：PostgreSQL（业务数据）+ Redis（缓存/消息队列）+ Milvus（向量检索）
- **异步任务**：Celery + Redis Beat（定时督促）
- **大模型**：DeepSeek（默认）+ Ollama（本地备选），统一走 OpenAI 兼容适配层
- **前端**：Next.js（React）
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
│   │   ├── agents/             # 智能体提示词与角色
│   │   ├── workflows/          # LangGraph 工作流编排
│   │   ├── knowledge/          # 向量库与 RAG
│   │   ├── tasks/              # Celery 定时任务
│   │   └── api/                # FastAPI 路由
│   ├── alembic/                # 数据库迁移
│   └── tests/
└── frontend/                   # Next.js 工作台
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

配置体系内置兜底，可在没有 Docker、没有大模型密钥的情况下完整跑通测试：

- `DATABASE__URL=sqlite+aiosqlite:///./data/kaoyan.db`
- `VECTOR__BACKEND=local`（本地向量兜底实现，不依赖 Milvus）
- `CELERY__TASK_ALWAYS_EAGER=true`
- `LLM__DEFAULT_PROVIDER=stub`（离线桩，无需密钥）

### 4. 一键启动全部容器

```bash
docker compose --profile app up -d
```

### 国内网络加速

PyPI 直连较慢时，pip 会因拉取索引超时而报 `Could not find a version ... (from versions: none)`，改用国内镜像即可：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
npm config set registry https://registry.npmmirror.com
```

## 开发节点

| 节点 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 工程骨架、配置体系、Docker 编排、健康检查 | 已完成 |
| 2 | 学习数据模型与 Alembic 迁移 | 待开始 |
| 3 | 智能体提示词体系与结构化输出 | 待开始 |
| 4 | LangGraph 任务工作流编排 | 待开始 |
| 5 | CrewAI 多角色智能体 | 待开始 |
| 6 | Milvus 向量库与 RAG 检索 | 待开始 |
| 7 | Celery 提醒督促定时任务 | 待开始 |
| 8 | FastAPI 业务接口层 | 待开始 |
| 9 | LangFuse 可观测性接入 | 待开始 |
| 10 | Next.js 前端工作台 | 待开始 |
| 11 | 测试、镜像与部署文档 | 待开始 |
