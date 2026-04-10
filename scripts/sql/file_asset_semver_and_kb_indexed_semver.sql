-- 文件 content 语义版本、解析状态；知识库关联表记录入库时的 semver 快照。
-- 已有库执行；新库由 ORM create_all 即可。

-- 1) file_asset：语义版本与解析状态（保留原 version 列直至数据回填后再删）
ALTER TABLE file_asset
  ADD COLUMN semver_major INT NOT NULL DEFAULT 0 COMMENT 'MAJOR（重新上传 +1）' AFTER file_hash,
  ADD COLUMN semver_minor INT NOT NULL DEFAULT 0 COMMENT 'MINOR' AFTER semver_major,
  ADD COLUMN semver_patch INT NOT NULL DEFAULT 0 COMMENT 'PATCH（每次解析 +1；首传默认 0）' AFTER semver_minor,
  ADD COLUMN parse_status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'pending/parsed' AFTER semver_patch;

UPDATE file_asset
SET semver_major = 0,
    semver_minor = 0,
    semver_patch = 0,
    parse_status = IF(parsed_md_storage_key IS NOT NULL AND TRIM(parsed_md_storage_key) <> '', 'parsed', 'pending');

-- 2) 去掉「同目录同名多版本」唯一约束，允许同名多文件（以 id 区分）
ALTER TABLE file_asset DROP INDEX uq_file_version_in_folder;

ALTER TABLE file_asset DROP COLUMN version;

CREATE INDEX idx_file_parse_status ON file_asset (owner_user_id, parse_status);

-- 3) knowledge_base_file：入库时快照 semver（用于「有新版本可更新」）
ALTER TABLE knowledge_base_file
  ADD COLUMN indexed_semver_major INT NULL COMMENT '入库快照 MAJOR' AFTER indexed_at,
  ADD COLUMN indexed_semver_minor INT NULL COMMENT '入库快照 MINOR' AFTER indexed_semver_major,
  ADD COLUMN indexed_semver_patch INT NULL COMMENT '入库快照 PATCH' AFTER indexed_semver_minor;

UPDATE knowledge_base_file kbf
INNER JOIN file_asset fa ON fa.id = kbf.file_id
SET kbf.indexed_semver_major = fa.semver_major,
    kbf.indexed_semver_minor = fa.semver_minor,
    kbf.indexed_semver_patch = fa.semver_patch
WHERE kbf.pipeline_status = 'indexed';
