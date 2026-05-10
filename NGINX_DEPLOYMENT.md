# Nginx 集成部署指南

## 📊 架构变更

### 原架构
```
客户端
  ├─> 8888 (FastAPI)
  └─> 3000 (Web)
```

### 新架构（推荐）
```
客户端
  └─> 80 (Nginx)
      ├─> 8888 (FastAPI - 仅内部)
      └─> 3000 (Web - 仅内部)
```

## 🚀 快速启动

### 生产环境（使用 Nginx）
```bash
docker-compose -f docker-compose.prod.yml up -d
# 访问：http://localhost
```

### 访问说明
| 路径 | 目标 | 端口 |
|------|------|------|
| `/api/*`, `/v1/*` | FastAPI API | 80 |
| `/ws/*` | WebSocket | 80 |
| `/docs`, `/redoc` | FastAPI 文档 | 80 |
| `/` | Next.js Web | 80 |
| `/health` | 健康检查 | 80 |

## 📝 Nginx 配置要点

### 文件位置
- **配置文件**：`./nginx.conf`
- **日志目录**：`./nginx_logs/`（自动挂载）

### 关键配置
```nginx
# API 路由
location /api/ → fastapi:8888
location /v1/  → fastapi:8888

# WebSocket 支持
location /ws/ → fastapi:8888 (无超时)

# 前端
location / → web:3000
```

## 🔒 HTTPS 配置（可选，生产推荐）

### 1. 准备 SSL 证书
```bash
mkdir -p certs
# 将证书放入：
# - certs/cert.pem
# - certs/key.pem
```

### 2. 编辑 nginx.conf
取消注释底部的 HTTPS 配置，填入域名：
```nginx
server_name your-domain.com;
```

### 3. 在 docker-compose.prod.yml 中挂载证书
```yaml
volumes:
  - ./certs:/etc/nginx/ssl:ro
```

### 4. 重启 Nginx
```bash
docker-compose -f docker-compose.prod.yml restart nginx
```

## 🔍 故障排查

### 检查 Nginx 日志
```bash
docker logs nginx-proxy
# 或查看挂载的日志目录
tail -f ./nginx_logs/access.log
tail -f ./nginx_logs/error.log
```

### 验证配置语法
```bash
docker exec nginx-proxy nginx -t
```

### 测试健康检查
```bash
curl http://localhost/health
# 返回：ok
```

### 检查后端连接
```bash
# 从 Nginx 容器内测试
docker exec nginx-proxy wget -qO- http://fastapi:8888/health
docker exec nginx-proxy wget -qO- http://web:3000/
```

## 🎯 性能优化

### Nginx 已启用的优化
- ✅ **连接保活**：`keepalive 32` 复用连接
- ✅ **缓冲控制**：`proxy_buffering off` 流式传输
- ✅ **超时配置**：合理的连接/发送/读取超时
- ✅ **WebSocket 支持**：特殊处理无超时限制
- ✅ **客户端上传限制**：`client_max_body_size 100M`

### 进一步优化（可选）
在 `nginx.conf` 中添加：
```nginx
# 压缩响应
gzip on;
gzip_types text/plain text/css application/json application/javascript;
gzip_min_length 1000;

# 缓存静态资源（需要 Next.js 配置 Cache-Control 头）
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

## 📋 环境变量（无需更改）

Nginx 不需要环境变量配置，但如需改动路由规则，编辑 `nginx.conf` 后重启：
```bash
docker-compose -f docker-compose.prod.yml restart nginx
```

## 🔄 回滚到无 Nginx

如需撤销 Nginx 集成：

### 方式 1：停用 Nginx（快速）
```bash
docker-compose -f docker-compose.prod.yml stop nginx
# 直接访问原端口
# http://localhost:8888 (FastAPI)
# http://localhost:3000 (Web)
```

### 方式 2：完全移除（编辑 docker-compose.prod.yml）
1. 删除 `nginx` 服务定义
2. 恢复 FastAPI 的 `ports: ["8888:8888"]`
3. 恢复 Web 的 `ports: ["${WEB_HOST_PORT:-3000}:3000"]`
4. 删除 `nginx_logs` volume
5. `docker-compose -f docker-compose.prod.yml up -d`

## 📊 预期性能收益

| 场景 | 收益 |
|------|------|
| **跨域 API 调用** | 🟢 **显著提升**（减少 CORS 预检） |
| **Web + API 混合请求** | 🟢 **10-20% 提升**（单一入口） |
| **纯 API 调用** | 🟡 **1-2% 提升**（代理开销极小） |
| **前端静态资源** | 🟢 **快速返回**（Nginx 可配置缓存） |

## 🔗 相关文档
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [Nginx 官方文档](https://nginx.org/en/docs/)
- [Docker Compose 参考](https://docs.docker.com/compose/compose-file/)
