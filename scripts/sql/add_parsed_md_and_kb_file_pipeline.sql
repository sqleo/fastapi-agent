-- 一次性迁移：file_asset 增加解析中间件路径；knowledge_base_file 增加流水线状态（与 Redis 队列 + LlamaIndex 对齐）。
-- 已有库执行；新库由 ORM create_all 即可。

-- 1) 原文件与解析后的 Markdown 路径（相对 static/，固定目录 static/parsed_md/，如 parsed_md/用户/文件.md）
ALTER TABLE file_asset
  ADD COLUMN parsed_md_storage_key VARCHAR(500) NULL COMMENT '相对 static/，位于 static/parsed_md/ 下'
  AFTER storage_key;

CREATE INDEX idx_file_asset_parsed_md_storage_key ON file_asset (parsed_md_storage_key);

-- 2) 知识库-文件关联上的流水线状态
ALTER TABLE knowledge_base_file
  ADD COLUMN pipeline_status VARCHAR(32) NOT NULL DEFAULT 'pending_md' COMMENT 'pending_md/ready_to_index/queued/indexing/indexed/failed'
  AFTER file_id;

ALTER TABLE knowledge_base_file
  ADD COLUMN pipeline_error VARCHAR(2000) NULL COMMENT '流水线失败原因'
  AFTER pipeline_status;

ALTER TABLE knowledge_base_file
  ADD COLUMN indexed_at DATETIME NULL COMMENT '在该知识库下最近一次索引成功时间'
  AFTER pipeline_error;

ALTER TABLE knowledge_base_file
  ADD COLUMN chunk_count INT NULL COMMENT '最近一次成功写入的 chunk 数'
  AFTER indexed_at;

CREATE INDEX idx_kb_file_pipeline ON knowledge_base_file (owner_user_id, pipeline_status);
