# Report Agent API 接口说明

Report Agent 提供了自动化的报告生成能力，支持长流程的异步执行、人工干预、状态恢复及回滚。

- **Base URL**: `/report`
- **鉴权**: 所有接口均需携带 `Authorization: Bearer <access_token>`

---

## 接口列表

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| POST | `/generate` | 创建报告生成任务（SSE 流式输出执行状态） |
| POST | `/resume` | 恢复被中断的报告任务（人工审核后继续） |
| GET | `/status/{thread_id}` | 查询报告任务的当前状态与完整数据 |
| POST | `/rollback/{thread_id}/{target_node}` | 将报告任务回滚到指定历史节点 |
| GET | `/stream/{thread_id}` | 流式监听报告生成进度（简易版进度监听） |

---

## 1. 创建报告生成任务

**POST** `/report/generate`

启动一个新的报告生成流程。由于报告生成耗时较长，该接口采用 **Server-Sent Events (SSE)** 形式实时返回执行进度。

### 请求体 (GenerateReportRequest)

| 字段 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `user_query` | string | 是 | 用户查询主题，例如："2026年Q1新能源汽车市场分析" |
| `thread_id` | string | 否 | 可选。如果不传则自动生成 UUID；如果传了已有的 thread_id，则尝试恢复该会话 |

### SSE 事件流 (Event Stream)

| 事件类型 (`type`) | 数据字段 | 说明 |
| :--- | :--- | :--- |
| `start` | `thread_id` | 流程开始 |
| `node_start` | `node` | 某个节点开始执行 |
| `node_end` | `node`, `output` | 某个节点执行完成，返回该节点的输出数据 |
| `tool_start` | `tool`, `input` | 工具调用开始 |
| `tool_end` | `tool`, `output` | 工具调用结束 |
| `message` | `data: {content}` | 模型生成的文本片段（流式输出内容） |
| `interrupted` | `thread_id`, `payload` | 流程中断（通常是需要人工审核），`payload` 包含审核所需数据 |
| `done` | `thread_id` | 流程正常结束 |
| `error` | `message` | 执行过程中发生异常 |

---

## 2. 恢复中断的任务

**POST** `/report/resume`

当流程进入 `interrupted` 状态后，用户通过此接口提交反馈，驱动流程继续。

### 请求体 (ResumeReportRequest)

| 字段 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `thread_id` | string | 是 | 会话 ID |
| `action` | string | 是 | 用户选择的操作，如：`confirm` / `revise` / `replan` |
| `updates` | dict | 否 | 额外更新的数据。例如修改了提纲后，将新提纲传回 |

### 响应 (SuccessResponse[GenerateReportResponse])

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "thread_id": "uuid",
        "status": "completed",
        "result": { ... }
    }
}
```

- 若恢复后再次触发中断，`status` 为 `interrupted`，并返回新的 `interrupt_payload`。

---

## 3. 查询报告状态

**GET** `/report/status/{thread_id}`

获取当前任务的运行状态及完整状态数据（State）。

### 响应 (SuccessResponse[ReportStatusResponse])

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `thread_id` | string | 会话 ID |
| `status` | string | `running` / `interrupted` / `completed` / `not_found` |
| `current_node` | list[str] | 待执行或正在执行的节点列表 |
| `state` | dict | 当前流程的完整 State 数据 |

---

## 4. 回滚任务

**POST** `/report/rollback/{thread_id}/{target_node}`

利用 LangGraph 的 Checkpoint 能力，将任务状态回退到历史的某个节点。

### 路径参数

- `thread_id`: 会话 ID
- `target_node`: 目标节点名称（如 `planner`, `researcher`）

### 响应

成功回滚后返回确认信息，之后可以重新调用 `resume` 或 `generate` 继续执行。

---

## 5. 进度流监听 (简易)

**GET** `/report/stream/{thread_id}`

另一种形式的 SSE 接口，主要用于被动监听节点完成状态，不触发执行。

### SSE 事件

- `event: node_complete`: 节点完成，data 为节点输出
- `event: completed`: 流程结束
- `event: interrupted`: 流程中断
- `event: error`: 发生错误
