# 报告生成 Agent API 接口文档

> 前端对接参考文档 | 最后更新: 2026-04-21

## 统一响应格式

所有接口统一返回以下结构：

### 成功响应
```json
{
  "code": 0,
  "message": "success",
  "data": { /* 业务数据 */ }
}
```

### 错误响应
```json
{
  "code": 40401,
  "message": "会话 xxx 不存在",
  "data": null
}
```

| 业务错误码 | 说明 |
|-----------|------|
| 0 | 成功 |
| 40001 | 请求参数错误 |
| 40401 | 资源不存在 |
| 50001 | 服务器内部错误 |

---

## 接口列表

### 1. 创建报告生成任务
```
POST /api/v1/report/generate
```

#### 请求体
```json
{
  "user_query": "2026年Q1新能源汽车市场分析",
  "thread_id": "可选，指定会话ID用于恢复执行"
}
```

#### 响应数据
```json
{
  "thread_id": "uuid-string",
  "status": "running / interrupted / completed",
  "current_node": "human_review",
  "interrupt_payload": { /* 中断时的审核数据 */ },
  "result": { /* 完成时的报告结果 */ }
}
```

---

### 2. 恢复中断的报告任务
```
POST /api/v1/report/resume
```

#### 请求体
```json
{
  "thread_id": "会话ID",
  "action": "confirm / revise / replan",
  "updates": {
    "outline": ["修改后的大纲", "可选"]
  }
}
```

#### 响应数据
同生成接口响应格式

---

### 3. 查询报告状态
```
GET /api/v1/report/status/{thread_id}
```

#### 响应数据
```json
{
  "thread_id": "uuid-string",
  "status": "running / interrupted / completed / not_found",
  "current_node": ["human_review"],
  "state": { /* 完整状态数据 */ }
}
```

---

### 4. 回滚报告到指定节点
```
POST /api/v1/report/rollback/{thread_id}/{target_node}
```

#### 路径参数
- `thread_id`: 会话ID
- `target_node`: 目标节点名称 `intent / researcher / outliner / planner / writer`

#### 响应数据
```json
{
  "thread_id": "uuid-string",
  "rollback_to": "researcher",
  "status": "ok"
}
```

---

### 5. 流式获取报告生成进度
```
GET /api/v1/report/stream/{thread_id}
```

> Server-Sent Events 流式接口

#### 事件类型
| 事件 | 说明 |
|------|------|
| `node_complete` | 节点执行完成 |
| `completed` | 报告生成完成 |
| `interrupted` | 执行中断，等待人工审核 |
| `error` | 执行出错 |

---

## 状态流转说明

```
created → running → interrupted ↔ resume → running → completed
                          ↓
                      rollback → 回到指定节点重新执行
```

### 状态说明
- `running`: 报告正在生成中
- `interrupted`: 流程中断，需要用户操作
- `completed`: 报告生成完成
- `not_found`: 会话不存在

---

## 对接注意事项

1. 所有接口需要携带认证 Token 在 Header 中
2. thread_id 是会话唯一标识，所有操作都需要这个ID
3. 中断状态下需要调用 resume 接口继续执行
4. 流式接口用于实时展示生成进度
5. 回滚接口用于纠正生成过程中的错误