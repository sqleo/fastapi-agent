# Copilot Instructions for FastAPI-Agent Codebase

## 📋 Module Update Summary

**Last Updated**: 2026-04-18

| Module | Section | Updates |
|--------|---------|---------|
| LangGraph CLI | Critical Workflows | Added graph structure patterns, middleware order, RunnableConfig usage, AGENT.md prompt loading |
| FastAPI | Critical Workflows | Added router patterns, async handlers, dependency injection, session management, auth flow, error handling |
| Memory | Agent Memory | Added advanced memory manager, short-term window, layered summarization, and configurable memory nodes |

**Changes Made**:
- ✅ Expanded "Critical Workflows" with LangGraph CLI development patterns
- ✅ Added "FastAPI Development Conventions" covering routers, handlers, database access, authentication, and request/response flow
- ✅ Documented LangGraph-FastAPI integration (SDK calls, thread management, stream modes, tool visibility)
- ✅ Added advanced memory management notes for `agent.memory` with LangMem store and configurable retrieval/write nodes

---

## Architecture Overview

**FastAPI Agent** is a multi-service system combining FastAPI (business logic) with LangGraph (agentic workflows) and LlamaRAG (document processing). Services communicate via HTTP, share PostgreSQL for checkpoints, and use async patterns throughout.

**Key Services:**
- **FastAPI** (`src/services/main_app.py`): HTTP API, auth, routing to `/v1/*` prefix
- **LangGraph** (`langgraph.json`): Two graphs defined: `agent`, `graph_service`
- **LlamaRAG** (`src/llamarag/`): Document parsing worker (Taskiq queue), Milvus vectorstore, LlamaIndex storage
- **Databases**: MySQL (business data), PostgreSQL (checkpoints + LlamaIndex docstore), Milvus (embeddings), Redis (queues)

## Code Organization

```
src/
├── agent/              # LangGraph integration & utilities
│  ├── core/graph.py    # Main agent graph definition
│  ├── control/         # Interrupts, time-travel, checkpoint control
│  ├── memory/          # LangMem integration (get_langgraph_store)
│  ├── tools/           # Tool catalog
│  └── middleware/      # Custom middleware for LangGraph
├── services/           # FastAPI application layer
│  ├── create_app.py    # App factory + lifespan (DB init, monitor setup)
│  ├── routers/         # API endpoints (auth, agent, file_management, knowledge_base, etc.)
│  ├── controllers/     # Business logic delegation
│  └── middlewares/     # HTTP middleware (require_login, CORS, logging)
├── llamarag/           # Document ingestion pipeline
│  ├── parse/           # MD/docx parsing
│  ├── ingestion/       # Chunk + embed to Milvus
│  ├── local_model/     # BGE embedding model wrapper
│  ├── worker/          # Taskiq broker & tasks (llamarag:parse queue)
│  └── storage/         # Postgres docstore & index store
├── models/             # SQLModel ORM entities (SQLAlchemy)
├── schemas/            # Pydantic request/response schemas
├── repositories/       # Data access layer (async SQLAlchemy queries)
└── utils/              # Shared: logging, JWT, SQL session, response formatting
```

## Critical Workflows

### Local Development (Hot Reload)
```bash
cp .env.example .env && make format && make lint
docker-compose -f docker-compose.dev.yml up
# FastAPI reloads on src/ changes; LlamaRAG worker auto-restarts
# Access: FastAPI :8888/docs, LangGraph :8123 (web UI)
```

### Testing
- **Unit tests**: `make test` or `pytest tests/unit_tests/`
- **Integration tests**: `make integration_tests` (test_graph.py uses LangGraph SDK)
- **Watch mode**: `make test_watch` (auto-reload on .py changes)
- **Linting**: `make lint` (ruff + mypy strict mode)

### LangGraph CLI Development Workflow

**Defined in `langgraph.json`:**
- **Graphs** are exported from Python: `agent`, `graph_service`
- **Checkpointer**: PostgreSQL (stateful conversation history, time-travel, resumption)
- **CLI commands**:
  - `langgraph dev` — local testing with hot reload (connects to `.env`)
  - `langgraph test` — run langgraph test scripts
  - `langgraph build` — create Docker image from `Dockerfile.langgraph`

**Graph Structure Patterns:**
- Graphs are built with `create_agent()` + middleware pipeline (see `src/agent/core/graph.py`)
- Middleware order matters: `strip_tool_calls` → `filter_tools` → `short_term_message_window` → `token_level_pause` → `inject_llm_from_global_settings`
- Advanced memory integration is implemented for the remaining graphs; compatibility with extra legacy graphs is not required for this change.
- All graphs access `RunnableConfig.configurable` for `user_id` (required), `enabled_tools` (optional filter list)
- System prompt loaded from `AGENT.md` at runtime; fallback to hardcoded default

**Integration with FastAPI:**
- FastAPI calls LangGraph via HTTP SDK (`langgraph_sdk.get_client`) to `LANGGRAPH_API_URL`
- Thread management: `thread_id` nullable; None creates new thread, provided ID resumes
- Stream modes: `messages-tuple,values,updates,custom` (configurable via `LANGGRAPH_AGENT_STREAM_MODES`)
- Tool visibility: `hidden_from_client_tool_names` excludes tools from client UI; `merge_enabled_with_hidden` controls what graph can invoke

### FastAPI Development Conventions

**Routers & Handlers:**
- **All handlers are `async def`** — FastAPI dependency injection (`Depends()`) for session, auth
- **Request/Response**: Use Pydantic `BaseModel` in `schemas/` directory; each router owns its schemas
- **Endpoint pattern**: `/v1/{domain}/{endpoint}` (e.g., `/v1/agent/chat/stream`)
- **Status codes**: Use `HTTPException(status_code=...)` for errors; `SuccessResponse` wrapper for OK responses

**Controllers Decoupling (Important):**
- **Prefer decoupling first** when adding or modifying controllers: split orchestration from domain logic.
- **One controller, one responsibility**: avoid mixing knowledge-base workflow, ingestion, and entity-review logic in the same module.
- **Extract reusable domain operations** into separate controller/service modules (e.g., entity candidate upsert, review actions).
- **Controller methods should orchestrate only**: validate input, call domain functions, handle transaction boundaries and response mapping.

**Entity Dictionary Conventions (Cross-Business Scope):**
- Keep **3-table separation** for entity workflow:
  - `entity_dictionary`: approved canonical entities only
  - `entity_alias`: approved aliases only
  - `entity_candidate`: pending/review workflow only
- Use scope fields on all entity tables: `owner_user_id` (required), `biz_code` (optional), `knowledge_base_id` (optional).
- Resolution priority must be:
  1) KB-level (`knowledge_base_id` matched)
  2) Biz-level (`biz_code` matched and `knowledge_base_id is null`)
  3) Global-level (`biz_code is null and knowledge_base_id is null`)
- Do **not** use `entity_candidate` directly in online retrieval resolution.
- Candidate ingestion should happen after metadata extraction and before review:
  - source fields: `product_name`, `brand`, `category`, `ingredients`, `keywords`
  - dedup key: `owner_user_id + biz_code + knowledge_base_id + file_id + candidate_normalized`
- Review actions:
  - approve: write/update `entity_dictionary` + `entity_alias`
  - reject: set candidate status to `rejected`
  - merge: set candidate status to `merged` and bind `approved_entity_id`

**Session & Database Access:**
- **Dependency**: `session: AsyncSqlSessionDeps` (injected from `get_async_session()`)
- **Transaction pattern**: `async with async_engine.begin() as conn: await conn.run_sync(...)`
- **ORM**: SQLModel (single definition for DB schema + Pydantic schema)
- **Repository layer**: Call repository methods, not raw SQL, for testability

**Authentication:**
- **Middleware**: `RequireLoginMiddleware` (added before CORS) enforces JWT token
- **Public routes**: Excluded via `PUBLIC_PATHS` in middleware
- **Current user**: Injected via `CurrentUserDeps` (extracts from JWT token)

**Error Handling & Logging:**
- **Global handlers**: `register_exception_handlers(app)` catches all domain exceptions
- **Logging**: Use `logging.getLogger(__name__)` in each module; `configure_logging()` sets up root handlers on startup
- **Access logs**: `access_log_middleware` logs method, path, status, latency (ms)

**Request/Response Flow:**
1. Incoming request → Pydantic schema validation (400 if invalid)
2. `RequireLoginMiddleware` checks JWT (401 if missing/expired)
3. Handler calls repository/service logic
4. Return `SuccessResponse(data=...)` or raise `HTTPException`
5. Exception handler formats error response with standard structure

### Key Configuration
- **`.env`**: Database URIs, LLM keys, JWT secret, model paths
  - `LLAMARAG_PROJECT_ROOT`: Used by embed_model; default resolves to project root
  - `BGE_LOCAL_MODEL_PATH`: If set, prioritized over HuggingFace Hub
  - `POSTGRES_URI`: Shared for checkpoints + LlamaIndex (different schemas OK)
- **`langgraph.json`**: Graph definitions, checkpointer config, env file reference

## Project-Specific Patterns

### Async-First Codebase
- All FastAPI handlers are `async def`
- Use `async with async_engine.begin() as conn` for transactions
- MySQL uses `aiomysql`, PostgreSQL uses `aiopg` (via langgraph-checkpoint-postgres)
- Never block async code; offload parsing to Taskiq worker queue

### Request-to-LangGraph Flow
1. FastAPI receives request → validates schema (Pydantic)
2. Calls LangGraph SDK (HTTP to `LANGGRAPH_API_URL`) with context/input
3. LangGraph invokes tools, reads Milvus vectors, manages checkpoints
4. Response streams back to FastAPI → client

### Database Session Management
- [sql_db.py](src/utils/sql_db.py): Creates `async_engine`, session factory
- Use dependency injection: `Depends(get_async_session)` in routers
- [create_app.py](src/services/create_app.py): Auto-creates tables on startup
- **Monitor database** (PostgreSQL): Separate pool in [monitor/pg.py](src/monitor/pg.py) for LLM analytics

### Error Handling & Responses
- [response.py](src/utils/response.py): Exception handlers registered in `create_app()`, formats all responses
- Standard 401 (unauthorized), 400 (validation), 500 (server error)
- [RequireLoginMiddleware](src/services/middlewares/require_login_middleware.py): Enforces JWT auth (public routes excluded)

### File Upload & LlamaRAG Integration
- [file_management.py](src/services/routers/file_management.py): CRUD endpoints for file metadata
- Upload → async task queued to `llamarag:parse`
- [Worker](src/llamarag/worker/taskiq_tasks.py) parses (MD, docx, etc.) → chunks → embed with BGE → store in Milvus
- File lifecycle: `uploaded` → `parsing` → `parsed` → `indexed`

### Memory & Tool Integration
- [LANGMEM_TOOLS](src/agent/memory/langmem.py): LangMem integration for persistent memory
- [tool_catalog](src/agent/tools/__init__.py): Declare custom tools for graph to invoke
- Tools are bound to graph nodes; access via `state.tools` or direct invocation

## Conventions & Decision Points

### Code Style
- **Python 3.10+**: Use type hints everywhere (mypy strict mode enforced)
- **Async/await**: Prefer async context managers (`async with`) over callbacks
- **Naming**: Routers use `router` (FastAPI APIRouter), functions are `snake_case`, classes are `PascalCase`
- **Comments**: Docstrings for public APIs; inline comments only for non-obvious logic

### Common Pitfalls
1. **Milvus URI in containers**: Use service name (`http://milvus:19530`), not localhost; see [docker-compose.dev.yml](docker-compose.dev.yml#L17)
2. **BGE model loading**: Ensure `LLAMARAG_PROJECT_ROOT` is set correctly in containers; defaults to project root
3. **PostgreSQL schemas**: LangGraph checkpointer and LlamaIndex storage can coexist in same DB with different schemas
4. **Middleware order**: `RequireLoginMiddleware` before CORS in [create_app.py](src/services/create_app.py#L103)—ensures 401 includes CORS headers

### Tools & Integrations
- **LangChain**: Runnable protocol, LCEL for prompt templating
- **LangGraph**: Stateful graph execution, built-in checkpointing, interrupt/resume patterns
- **LlamaIndex**: Document chunking, embedding, vector search—NOT for Agent memory (use LangMem instead)
- **Taskiq**: Lightweight task queue; parse jobs pushed to Redis, worker consumes `llamarag:parse`
- **SQLModel**: Combines SQLAlchemy ORM + Pydantic; define once, use for both DB schema and API responses

## Key Files to Know
- [Agent graph](src/agent/core/graph.py): Entry point for agentic workflow logic
- [FastAPI routers](src/services/routers/): Each router handles a domain (auth, file_management, knowledge_base, etc.)
- [Database session factory](src/utils/sql_db.py): Centralized async engine + session dependency
- [LlamaRAG worker](src/llamarag/worker/taskiq_tasks.py): Async document processing pipeline
- [Embedding model](src/llamarag/local_model/embed_model.py): BGE wrapper with fallback to HuggingFace Hub
- [Config](configs/env.py): All environment variables documented with descriptions

## Quick Checklist for New Features
- [ ] Add schema to [schemas/](src/schemas/) (request/response)
- [ ] Add model to [models/](src/models/) if new DB entity
- [ ] Create or extend router in [routers/](src/services/routers/) → include in [main_app.py](src/services/main_app.py)
- [ ] Add repository methods in [repositories/](src/repositories/) for data access
- [ ] If async work (file parsing): queue task to [worker](src/llamarag/worker/taskiq_tasks.py)
- [ ] Add integration tests in [tests/integration_tests/](tests/integration_tests/)
- [ ] Run `make format && make lint` before commit
