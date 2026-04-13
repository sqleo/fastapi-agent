# FastAPI Agent — HTTP 接口说明

- **Base URL**：本地默认 `http://127.0.0.1:8888`（以实际部署为准）。
- **统一响应**：业务成功时 `code === 0`，数据在 `data`；失败时 `code !== 0`，见 `message`。
- **鉴权**：除「公开接口」外，请求头需携带 `Authorization: Bearer <access_token>`（登录接口返回的 `access_token`）。

```json
{ "code": 0, "message": "success", "data": { } }
```

---

## 公开接口（无需登录）


| 方法   | 路径                         | 说明                 |
| ---- | -------------------------- | ------------------ |
| GET  | `/`                        | 重定向到 `/docs`       |
| GET  | `/ok`                      | 健康检查，返回 `"ok"`     |
| GET  | `/docs`                    | Swagger UI         |
| GET  | `/redoc`                   | ReDoc              |
| POST | `/auth/register`           | 用户注册               |
| POST | `/auth/login`              | 登录，获取 JWT          |
| GET  | `/llm/vendors/marketplace` | LLM 厂商市场列表（未安装前展示） |


---

## 认证  `/auth`


| 方法   | 路径               | 鉴权  | 说明                   |
| ---- | ---------------- | --- | -------------------- |
| POST | `/auth/register` | 否   | 注册新用户                |
| POST | `/auth/login`    | 否   | 登录，返回 `access_token` |
| GET  | `/auth/me`       | 是   | 当前用户信息               |


---

## Agent  `/agent`

依赖 **LangGraph 服务**（环境变量 `LANGGRAPH_API_URL`，默认 `http://localhost:8123`）。通用助手聊天通过 SDK 调用远程图 `assistant_id="agent"`；**智能客服** 使用 `assistant_id="customer_service"`（见下文「智能客服」）。

### 工具列表与开关（默认：未保存偏好 = **全部工具开启**）

**基础工具（不返回前端）**：在代码里用装饰器 `@hidden_from_client` 标注（写在 `@tool` 上方），或对第三方创建的 Tool 调用 `hidden_from_client(tool_obj)`。这些工具不会出现在 `GET /agent/tools`；`enabled_tools` 在服务端会与其 **取并集**，避免被关闭。


| 方法  | 路径                      | 说明                                                                                                            |
| --- | ----------------------- | ------------------------------------------------------------------------------------------------------------- |
| GET | `/agent/tools`          | 返回**对前端暴露**的工具及每项 `enabled`（与 `PUT /agent/tools/settings` 保存的偏好一致）                                            |
| PUT | `/agent/tools/settings` | 保存用户级工具开关；请求体 `{ "enabled_tools": ["工具名", ...] | null }`。`null` 表示删除保存、恢复默认全开；`[]` 表示对前端可见工具全部禁用（隐藏的基础工具仍会启用） |


### 对话


| 方法   | 路径                   | 说明                                                              |
| ---- | -------------------- | --------------------------------------------------------------- |
| POST | `/agent/chat`        | 非流式对话；请求体含 `message`、`thread_id`（可选）、`enabled_tools`（可选，见下）     |
| POST | `/agent/chat/stream` | **SSE** 流式；`Content-Type: text/event-stream`，每条 `data:` 后为 JSON |


**聊天请求体 `ChatRequest`**


| 字段              | 类型              | 说明                                                                    |
| --------------- | --------------- | --------------------------------------------------------------------- |
| `message`       | string          | 用户消息                                                                  |
| `thread_id`     | string | null   | 不传则新建线程；传则续聊                                                          |
| `enabled_tools` | string[] | null | 不传：使用 `PUT /agent/tools/settings` 保存的偏好；从未保存：**默认全开**；`[]`：本次请求禁用全部工具 |


**SSE 事件类型（示例）**：`start`、`thinking`、`text`、`tool`、`reference`、`paused`、`error`、`done`（以实际流为准）。

### 智能客服  `/agent/customer-service`

与通用 `/agent/chat` 行为类似，但固定调用 LangGraph 图 `**customer_service`**（系统提示由 `src/prompts/shared/templates/` 与 `src/prompts/products/customer_service/templates/` 下 Jinja 模板经 `prompts.products.customer_service.build_customer_service_system_prompt` 渲染，入口为 `compose.j2`；环境变量 `CS_TICKET_PATH` / `CS_HUMAN_SUPPORT_PATH` 可覆盖工单与人工入口路径）。默认仅启用工具 `**knowledge_base_search**`（知识库向量检索）及 LangMem（`manage_memory`、`search_memory`）；`enabled_tools` 不传时使用该默认集合，且会与 LangMem 工具名自动合并。


| 方法   | 路径                                    | 说明                                                    |
| ---- | ------------------------------------- | ----------------------------------------------------- |
| POST | `/agent/customer-service/chat`        | 非流式；请求体：`message`、`thread_id`（可选）、`enabled_tools`（可选） |
| POST | `/agent/customer-service/chat/stream` | SSE 流式                                                |


建议为智能客服**单独使用** `thread_id`，勿与通用 Agent 会话混用同一线程。

**按 Agent 的采样温度**：路由在调用 LangGraph 时会根据 `assistant_id` 写入 `configurable.llm_temperature`。可通过环境变量覆盖内置默认（未设置环境变量时：通用 `agent` 不覆盖温度，仍走厂商 `extra_config`；`customer_service` 默认 `0.2`）：

- `LANGGRAPH_TEMPERATURE_AGENT`：通用助手
- `LANGGRAPH_TEMPERATURE_CUSTOMER_SERVICE`：智能客服

设置后**优先于**厂商 `extra_config.temperature`。详见 `src/utils/agent_temperature.py`。

### 对话控制与时间旅行


| 方法     | 路径                                | 说明                             |
| ------ | --------------------------------- | ------------------------------ |
| DELETE | `/agent/chat/{thread_id}`         | 删除 LangGraph 线程及关联数据           |
| POST   | `/agent/chat/{thread_id}/pause`   | 暂停生成（可选 body：`PauseRequest`）   |
| POST   | `/agent/chat/{thread_id}/resume`  | 继续生成（可选 body：`ResumeRequest`）  |
| GET    | `/agent/chat/{thread_id}/history` | 获取 checkpoint 列表（时间旅行）         |
| POST   | `/agent/chat/{thread_id}/travel`  | 时间旅行（body：`TimeTravelRequest`） |


---

## LLM 厂商  `/llm/vendors`


| 方法    | 路径                                   | 鉴权  | 说明        |
| ----- | ------------------------------------ | --- | --------- |
| GET   | `/llm/vendors/marketplace`           | 否   | 厂商市场      |
| GET   | `/llm/vendors/installed`             | 是   | 当前用户已安装厂商 |
| POST  | `/llm/vendors/install/{vendor_code}` | 是   | 安装厂商      |
| PATCH | `/llm/vendors/{vendor_id}`           | 是   | 更新已安装厂商配置 |


---

## LLM 全局设置  `/llm/settings`


| 方法    | 路径                               | 说明                                                                                              |
| ----- | -------------------------------- | ----------------------------------------------------------------------------------------------- |
| GET   | `/llm/settings/available-models` | 可选模型列表；Query `capability`：`LLM` / `Embedding` / `Rerank` / `VLM` / `ASR` / `TTS` / `Moderation` |
| GET   | `/llm/settings/global`           | 获取当前用户全局模型设置                                                                                    |
| PATCH | `/llm/settings/global`           | 更新全局模型设置                                                                                        |


---

## 监控  `/monitor`

数据来自 PostgreSQL `llm_monitor` schema（需配置 `POSTGRES_URI` / `MONITOR_POSTGRES_URI`）。未配置时接口仍返回成功，`data` 多为空或零值。

**趋势类接口** Query：`period`，取值 `realtime` | `day` | `week` | `month`（默认 `day`）。


| 方法  | 路径                             | 说明                                                                 |
| --- | ------------------------------ | ------------------------------------------------------------------ |
| GET | `/monitor/overview`            | 概览：请求数、Token、成功率、延迟、活跃会话、缓存命中率等                                    |
| GET | `/monitor/trends/requests`     | 请求量趋势（图表：`date` / `value` / `category`）                            |
| GET | `/monitor/trends/tokens`       | Token 趋势（`input_cache_hit` / `input_cache_miss` / `output_tokens`） |
| GET | `/monitor/trends/latency`      | 延迟趋势（`avg` / `p95`）                                                |
| GET | `/monitor/trends/success_rate` | 成功率趋势                                                              |
| GET | `/monitor/errors`              | 错误类型分布（饼图：`type` / `value`）                                        |
| GET | `/monitor/models`              | 按模型统计                                                              |
| GET | `/monitor/requests`            | 最近请求明细；Query `limit`（1–100，默认 20）                                  |


前端图表可参考 **@ant-design/charts**（折线、柱状、饼图等），字段已与上述结构对齐。

---

## 错误码（节选）


| HTTP | code（业务） | 常见场景          |
| ---- | -------- | ------------- |
| 401  | 40101    | 未登录或 Token 无效 |
| 422  | 42201    | 参数校验失败        |


完整模型定义以 `**/docs` OpenAPI** 为准；本文仅作导航与约定说明。