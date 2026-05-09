# LangMem 多租户记忆架构

## 目标

每个用户拥有：

- 独立的嵌入模型（vendor / model / dim）
- 独立的 PostgreSQL schema（`mem_u{user_id}_v{embedding_version}`）
- 独立的 pgvector 向量空间（维度互不影响）

且 LangGraph / LangMem 调用方完全无感——还是 `get_langgraph_store()` 那一个 store。

## 数据流

```
HTTP Request (user_id from JWT)
        │
        ▼
FastAPI Router  ──→  configurable.user_id = str(user_id)
        │
        ▼
LangGraph Agent (graph / graph_with_checkpoint)
        │ store=get_langgraph_store()
        ▼
TenantRoutingStore.abatch(ops)
        │  按 namespace[1] 解析 user_id 分组
        ▼
TenantStoreFactory.get_store_for_user(user_id)
        │  查 llm_global_setting → (version, status, dim)
        ▼
   ┌────┴─────┐
   │ active   │ → PostgresStore(schema=mem_u{uid}_v{ver}, embed=该用户的 LiteLLMEmbeddings)
   │ migrating│ → DualWriteStore(primary=v_new, secondary=v_old kv-only)
   │ deprecated│→ PostgresStore(schema=mem_u{uid}_v{ver}, index=None)（KV-only 降级）
   └──────────┘
        │
        ▼
PostgreSQL  各 schema 内：
  store          KV + 元数据
  store_vectors  pgvector(dim)，列宽=该用户 embedding_dim
```

## 关键约定

### namespace 第一段是分类前缀，**第二段必须是 `str(user_id)`**

| 调用方 | namespace |
|---|---|
| LangMem `manage_memory` / `search_memory` 工具 | `("agent_memories", "{user_id}", "{thread_id}")` |
| `AdvancedMemoryManager` | `("user_memories", str(user_id))` |
| `memory_retrieve_node` / `memory_write_node` | `("user_memories", str(user_id))` |

`TenantRoutingStore` 入口处校验 `namespace[1]` 必须是正整数；
否则直接抛 `InvalidNamespaceError`。绝对不会静默落到错误的 schema。

### `ListNamespacesOp` 不支持

跨租户列举不安全，路由层直接拒绝。业务代码也无任何路径调用它。

## 配置变更触发的迁移

```
1. 用户在「LLM 全局设置」改 embedding_vendor_id / embedding_model / embedding_dim
2. PUT /llm/settings/global → llm_global_setting_controller.update_global_setting_owned
3. 检测到 embedding_* 字段变更：
   - embedding_version: N → N+1
   - embedding_status: active → migrating
   - 清运行时缓存（store / embeddings / config）
   - 入队 reindex_user_memory(user_id, N, N+1)
4. Worker 进程拉到任务（队列 langmem:reindex）：
   - 创建新 schema mem_u{uid}_v{N+1}（store factory 自动建）
   - 流式读旧 schema mem_u{uid}_v{N}.store 全部记录
   - 用新 embedder 重算向量，aput 到新 schema
   - 全部完成 → status: migrating → active；DROP SCHEMA mem_u{uid}_v{N} CASCADE
   - 部分失败 → 保持 migrating，DualWriteStore 双写持续工作，等下次重试
```

迁移期：

- 新写入 → 双写（新+旧）
- 读 → 仅新 schema（避免读到旧向量空间数据）
- reindex 任务把旧记录回填进新 schema 后切回单写

## 启动 Worker

```bash
REDIS_URI=redis://localhost:6379/1 \
uv run taskiq worker infra.langgraph.reindex_tasks:broker
```

队列 `langmem:reindex` 与 LlamaRAG 的 `llamarag:parse` 隔离，两个 worker 互不干扰。

## 运维 Runbook

### 用户切换嵌入模型

不需要任何手动操作。改 `llm_global_setting` → controller 自动入队。

### Reindex 任务失败

任务保持 `embedding_status='migrating'`，前端继续可用（双写）。
排查思路：

1. 看日志 `infra.langgraph.reindex_tasks` 找具体失败 user_id 与异常
2. 修复后重新入队：

```python
from infra.langgraph.reindex_tasks import enqueue_reindex
await enqueue_reindex(user_id=123, old_version=2, new_version=3)
```

### 强制重建索引

直接改 `llm_global_setting` 把 `embedding_version` -1（让它"看起来又新了一次"），保存即可触发新版本号 +1。

### 清理孤儿 schema

```sql
SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'mem_u%';
```

对照 `llm_global_setting.embedding_version`，把 `< current_version` 的 schema `DROP CASCADE`。
（正常路径下 reindex 完成后会自动 DROP，此步骤仅为人工兜底。）

### 用户删除

DROP `llm_global_setting` 行 + 主动 `DROP SCHEMA mem_u{uid}_v* CASCADE`。

## 降级与灾难恢复

| 场景 | 行为 |
|---|---|
| 用户未配置嵌入 | KV-only：能存能取，但语义检索关闭 |
| Postgres 不可达 | LangMem 工具调用直接报错；建议 `LANGMEM_ENABLED=0` 关闭 |
| pgvector 扩展缺失 | 第一次建 schema 时报错，被 Taskiq 吞掉；建议预置 pgvector |
| Reindex 中断（worker 崩） | `embedding_status` 留 `migrating`，DualWriteStore 双写继续；重启 worker 后重新入队 |

## 代码索引

- `src/models/LlmGlobalSettingModel.py` —— 嵌入配置（vendor/model/dim/version/status）
- `src/llm_completion/embedding_llm.py` —— 嵌入工厂（按 (user_id, version) 缓存）
- `src/infra/langgraph/tenant_store.py` —— 多租户路由 + 双写 + 工厂
- `src/infra/langgraph/store.py` —— 唯一对外入口 `get_langgraph_store()`
- `src/infra/langgraph/reindex_tasks.py` —— Taskiq reindex 任务
- `src/services/controllers/llm_global_setting_controller.py` —— 触发 +1 + 入队
- `src/utils/schema_migrations.py` —— 启动时给 `llm_global_setting` 加 3 列
- `tests/integration_tests/test_tenant_store.py` —— 端到端集成测试
