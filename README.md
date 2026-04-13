# New LangGraph Project

This template demonstrates a simple application implemented using [LangGraph](https://github.com/langchain-ai/langgraph), designed for showing how to get started with [LangGraph Server](https://langchain-ai.github.io/langgraph/concepts/langgraph_server/#langgraph-server) and using [LangGraph Studio](https://langchain-ai.github.io/langgraph/concepts/langgraph_studio/), a visual debugging IDE.

The core logic defined in `src/agent/graph.py`, showcases an single-step application that responds with a fixed string and the configuration provided.

You can extend this graph to orchestrate more complex agentic workflows that can be visualized and debugged in LangGraph Studio.

## Getting Started

1. Install dependencies, along with the [LangGraph CLI](https://langchain-ai.github.io/langgraph/concepts/langgraph_cli/), which will be used to run the server.

```bash
cd path/to/your/app
pip install -e . "langgraph-cli[inmem]"
```

1. (Optional) Customize the code and project as needed. Create a `.env` file if you need to use secrets.

```bash
cp .env.example .env
```

If you want to enable LangSmith tracing, add your LangSmith API key to the `.env` file.

```text
# .env
LANGSMITH_API_KEY=lsv2...
```

1. Start the LangGraph Server.

```shell
langgraph dev
```

For more information on getting started with LangGraph Server, [see here](https://langchain-ai.github.io/langgraph/tutorials/langgraph-platform/local-server/).

## How to customize

1. **Define runtime context**: Modify the `Context` class in the `graph.py` file to expose the arguments you want to configure per assistant. For example, in a chatbot application you may want to define a dynamic system prompt or LLM to use. For more information on runtime context in LangGraph, [see here](https://langchain-ai.github.io/langgraph/agents/context/?h=context#static-runtime-context).
2. **Extend the graph**: The core logic of the application is defined in [graph.py](./src/agent/graph.py). You can modify this file to add new nodes, edges, or change the flow of information.

## Development

While iterating on your graph in LangGraph Studio, you can edit past state and rerun your app from previous states to debug specific nodes. Local changes will be automatically applied via hot reload.

Follow-up requests extend the same thread. You can create an entirely new thread, clearing previous history, using the `+` button in the top right.

For more advanced features and examples, refer to the [LangGraph documentation](https://langchain-ai.github.io/langgraph/). These resources can help you adapt this template for your specific use case and build more sophisticated conversational agents.

LangGraph Studio also integrates with [LangSmith](https://smith.langchain.com/) for more in-depth tracing and collaboration with teammates, allowing you to analyze and optimize your chatbot's performance.

## Architecture

```
                    ┌─────────────────────────────────────────────────┐
                    │              Docker Compose Network              │
                    │                                                  │
  用户请求           │  ┌──────────────────────────────────────────┐   │
    │               │  │             应用服务层                    │   │
    ▼               │  │                                          │   │
 ┌────────┐         │  │ ┌──────────────┐  SDK   ┌─────────────┐ │   │
 │ Client ├─:8888───┼──┼▶│   FastAPI     │──────▶│  LangGraph   ││   │
 └───┬────┘         │  │ │  (业务 API)   │       │  Platform    ││   │
     │              │  │ │              │       │  (Agent)     ││   │
     │ :8123        │  │ │ - 路由 / 鉴权 │       │             ││   │
     │ 可直接访问    │  │ │ - 业务逻辑    │       │ - tool-call  ││   │
     └──────────────┼──┼▶│              │       │ - 流式处理    ││   │
                    │  │ └──────┬───────┘       └──┬───┬───────┘│   │
                    │  └────────┼───────────────────┼───┼────────┘   │
                    │           │                   │   │            │
                    │  ┌────────┼───────────────────┼───┼────────┐   │
                    │  │        │     数据存储层     │   │        │   │
                    │  │        ▼                   ▼   ▼        │   │
                    │  │  ┌──────────┐  ┌────────┐  ┌────────┐  │   │
                    │  │  │  MySQL    │  │ Milvus │  │Postgres│  │   │
                    │  │  │  :3306   │  │ :19530 │  │ :5432  │  │   │
                    │  │  │ 业务数据  │  │向量检索 │  │ Check- │  │   │
                    │  │  │          │  │        │  │ point  │  │   │
                    │  │  └──────────┘  └────────┘  └────────┘  │   │
                    │  │  可选/第三方    可选/第三方   始终启动     │   │
                    │  └────────────────────────────────────────┘   │
                    └──────────────────────────────────────────────┘

  数据流:
  FastAPI ──MySQL──▶ 业务数据读写
  LangGraph Agent ──tool──▶ Milvus 向量检索（Agent 自主决定何时检索）
  LangGraph Agent ──────▶ PostgreSQL checkpoint 持久化
```


| 服务                 | 端口        | 说明                              |
| ------------------ | --------- | ------------------------------- |
| FastAPI            | 8888      | 业务 API 入口                       |
| LangGraph Platform | 8123      | Agent API（也可直接访问）               |
| PostgreSQL         | 5432      | 始终启动，LangGraph 必需               |
| MySQL              | 3306      | profile: mysql，可选 / 可用第三方       |
| Milvus             | 19530     | profile: milvus，可选 / 可用第三方      |
| MinIO (Milvus S3)  | 9000/9001 | Milvus 内部依赖，随 milvus profile 启动 |


## Quick Start

```bash
# 构建镜像（Agent 代码变更后需重新执行）
uv run langgraph build -t langgraph-agent:latest
docker compose --profile redis build fastapi kb-ingest-worker


# 全部本地部署（MySQL + Milvus 都启动）
docker compose --profile mysql --profile milvus up -d

# 仅 Milvus 本地，MySQL 用第三方
docker compose --profile milvus up -d

# 仅 MySQL 本地，Milvus 用第三方（如 Zilliz Cloud）
docker compose --profile mysql up -d

# 全部用第三方，只启动 FastAPI + LangGraph + PostgreSQL
docker compose up -d
```

```bash
# 开发：热更新（需已按上文构建好镜像）
docker compose -f docker-compose.dev.yml build fastapi
docker compose -f docker-compose.dev.yml up -d
```

