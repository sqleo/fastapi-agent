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

依赖 **LangGraph 服务**（环境变量 `LANGGRAPH_API_URL`，默认 `http://localhost:8123`）。通用助手聊天通过 SDK 调用远程图 `assistant_id="agent"`。

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


---

## Metadata 抽取配置  `/metadata-fields`

用于给 LlamaRAG 入库前的结构化 metadata 抽取提供动态规则。**实际完整路径需加统一前缀 `/v1`**。

### 作用域约定

- `knowledge_base_id` 有值：知识库级配置
- `knowledge_base_id` 为空且 `biz_code` 有值：业务级配置
- `knowledge_base_id` 与 `biz_code` 都为空：全局级配置

### 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/metadata-fields` | 查询某个作用域下的字段配置列表，返回字段及其别名 |
| POST | `/metadata-fields` | 新建字段配置，可同时写入初始化别名 |
| PATCH | `/metadata-fields/{field_id}` | 更新字段配置 |
| DELETE | `/metadata-fields/{field_id}` | 删除字段配置及其全部别名 |
| GET | `/metadata-fields/{field_id}/aliases` | 查询某个字段下的别名列表 |
| POST | `/metadata-fields/{field_id}/aliases` | 新增字段别名 |
| PATCH | `/metadata-fields/aliases/{alias_id}` | 更新字段别名 |
| DELETE | `/metadata-fields/aliases/{alias_id}` | 删除字段别名 |

### 字段枚举

- `value_type`：`text` / `number` / `list` / `date`
- `extract_mode`：`field` / `section`
- `match_mode`：`exact` / `contains` / `regex`
- `status`：`1` 启用，`0` 禁用

### 1）查询字段配置列表

**GET** `/v1/metadata-fields?knowledge_base_id=12`

Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `knowledge_base_id` | int | 否 | 知识库 id；不传表示查询非知识库级 |
| `biz_code` | string | 否 | 业务编码；不传表示查询全局级 |
| `status` | int | 否 | 按状态过滤：`1` / `0` |

响应示例：

```json
{
	"code": 0,
	"message": "查询成功",
	"data": {
		"total": 2,
		"items": [
			{
				"id": 101,
				"owner_user_id": 2,
				"biz_code": "nutrition",
				"knowledge_base_id": 12,
				"field_key": "product_name",
				"field_name": "产品名称",
				"value_type": "text",
				"extract_mode": "field",
				"status": 1,
				"priority": 10,
				"created_at": "2026-04-18 10:00:00",
				"updated_at": "2026-04-18 10:00:00",
				"aliases": [
					{
						"id": 1001,
						"field_id": 101,
						"alias_text": "产品名称",
						"match_mode": "exact",
						"status": 1,
						"priority": 10,
						"created_at": "2026-04-18 10:00:00",
						"updated_at": "2026-04-18 10:00:00"
					}
				]
			}
		]
	}
}
```

### 2）新建字段配置

**POST** `/v1/metadata-fields`

请求体示例：

```json
{
	"biz_code": "nutrition",
	"knowledge_base_id": 12,
	"field_key": "product_name",
	"field_name": "产品名称",
	"value_type": "text",
	"extract_mode": "field",
	"status": 1,
	"priority": 10,
	"aliases": [
		{
			"alias_text": "产品名称",
			"match_mode": "exact",
			"status": 1,
			"priority": 10
		},
		{
			"alias_text": "商品名称",
			"match_mode": "exact",
			"status": 1,
			"priority": 20
		}
	]
}
```

说明：

- `field_key` 建议前端统一传 snake_case
- 若 `knowledge_base_id` 传值，会校验该知识库是否属于当前用户
- `aliases` 可为空数组

### 3）更新字段配置

**PATCH** `/v1/metadata-fields/{field_id}`

请求体示例：

```json
{
	"field_name": "商品名称",
	"priority": 5,
	"status": 1
}
```

### 4）删除字段配置

**DELETE** `/v1/metadata-fields/{field_id}`

响应示例：

```json
{
	"code": 0,
	"message": "删除成功",
	"data": {
		"field_id": 101
	}
}
```

### 5）查询字段别名列表

**GET** `/v1/metadata-fields/{field_id}/aliases`

### 6）新增字段别名

**POST** `/v1/metadata-fields/{field_id}/aliases`

请求体示例：

```json
{
	"alias_text": "净含量",
	"match_mode": "contains",
	"status": 1,
	"priority": 30
}
```

### 7）更新字段别名

**PATCH** `/v1/metadata-fields/aliases/{alias_id}`

请求体示例：

```json
{
	"alias_text": "规格",
	"match_mode": "exact",
	"priority": 5
}
```

### 8）删除字段别名

**DELETE** `/v1/metadata-fields/aliases/{alias_id}`

### 前端对接建议

- 配置页先调用列表接口，按 `knowledge_base_id + biz_code` 展示当前作用域配置
- 创建字段时优先同时提交主别名，减少二次保存
- 入库按钮前可先调用列表接口判断 `total > 0`
- 若后端返回 `422` 且提示“未配置 metadata 抽取规则”，引导用户先完成该页面配置

---

## 实体候选审核  `/entity-candidates`

用于管理入库阶段抽取到的候选实体（`entity_candidate`），支持分页筛选与审核三动作。

### 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/entity-candidates` | 候选实体分页列表（默认仅返回 `pending`） |
| GET | `/entity-candidates/target-entities` | 合并弹窗目标实体下拉（用于 `target_entity_id`） |
| POST | `/entity-candidates/{candidate_id}/approve` | 审核通过（落库到 `entity_dictionary`，并补充别名） |
| POST | `/entity-candidates/{candidate_id}/reject` | 审核驳回 |
| POST | `/entity-candidates/{candidate_id}/merge` | 合并到已有正式实体 |

### 1）候选实体分页列表

**GET** `/v1/entity-candidates`

Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码，默认 `1` |
| `page_size` | int | 否 | 每页条数，默认 `20`，最大 `100` |
| `status` | string | 否 | 状态过滤：`pending/approved/rejected/merged`，默认 `pending` |
| `biz_code` | string | 否 | 业务编码；不传表示不按业务过滤 |
| `knowledge_base_id` | int | 否 | 知识库 id；不传表示不按知识库过滤 |
| `file_id` | int | 否 | 来源文件 id |
| `keyword` | string | 否 | 候选文本模糊搜索 |

响应示例：

```json
{
	"code": 0,
	"message": "查询成功",
	"data": {
		"total": 1,
		"page": 1,
		"page_size": 20,
		"items": [
			{
				"id": 9,
				"owner_user_id": 2,
				"biz_code": "nutrition",
				"knowledge_base_id": 1,
				"file_id": 10,
				"entity_type": "brand",
				"candidate_text": "WonderLab",
				"candidate_normalized": "wonderlab",
				"evidence": {"source": "ingestion.extract_doc_metadata"},
				"frequency": 2,
				"confidence": null,
				"status": "pending",
				"reviewer_user_id": null,
				"reviewed_at": null,
				"review_comment": null,
				"approved_entity_id": null,
				"created_at": "2026-04-18 12:00:00",
				"updated_at": "2026-04-18 12:00:00"
			}
		]
	}
}
```

### 2）审核通过

**POST** `/v1/entity-candidates/{candidate_id}/approve`

请求体示例：

```json
{
	"canonical_name": "WonderLab",
	"entity_type": "brand",
	"aliases": ["WL", "WonderLab官方"],
	"review_comment": "品牌词确认"
}
```

说明：

- 若同作用域同类型下已存在同 `normalized_name` 的正式实体，则复用该实体
- 会自动把候选文本作为别名补充到 `entity_alias`

### 3）审核驳回

**POST** `/v1/entity-candidates/{candidate_id}/reject`

请求体示例：

```json
{
	"review_comment": "噪音词，非业务实体"
}
```

### 4）审核合并

**POST** `/v1/entity-candidates/{candidate_id}/merge`

请求体示例：

```json
{
	"target_entity_id": 101,
	"review_comment": "同义词并入已有实体"
}
```

说明：

- 目标实体必须与候选实体同用户、同作用域（`biz_code` 与 `knowledge_base_id` 一致）
- 合并时会把候选文本补充为目标实体别名

### 5）合并目标实体下拉

**GET** `/v1/entity-candidates/target-entities`

Query 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `biz_code` | string | 否 | 业务编码；建议传当前候选的 `biz_code` |
| `knowledge_base_id` | int | 否 | 知识库 id；建议传当前候选的 `knowledge_base_id` |
| `entity_type` | string | 否 | 实体类型过滤：`product/brand/category/ingredient/other` |
| `keyword` | string | 否 | 标准实体名模糊搜索 |
| `limit` | int | 否 | 返回条数上限，默认 `50`，最大 `200` |

响应示例：

```json
{
	"code": 0,
	"message": "查询成功",
	"data": {
		"total": 2,
		"items": [
			{
				"id": 101,
				"canonical_name": "WonderLab",
				"entity_type": "brand",
				"biz_code": "nutrition",
				"knowledge_base_id": 1
			},
			{
				"id": 205,
				"canonical_name": "薄荷味能量棒",
				"entity_type": "product",
				"biz_code": "nutrition",
				"knowledge_base_id": 1
			}
		]
	}
}
```

完整模型定义以 `**/docs` OpenAPI** 为准；本文仅作导航与约定说明。