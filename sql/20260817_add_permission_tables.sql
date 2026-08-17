-- ============================================================
-- 權限管理功能：新增資料表與欄位 (PostgreSQL)
--
-- 執行方式：
--   psql -U <user> -d <database> -f sql/20260817_add_permission_tables.sql
--
-- 請在「重新啟動服務之前」執行。程式啟動時會檢查這些資料表，
-- 若不存在會印出提示並略過權限初始化。
--
-- 本腳本可重複執行 (idempotent)。
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. 權限群組
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permission_groups (
    id          SERIAL       PRIMARY KEY,
    name        VARCHAR(80)  NOT NULL UNIQUE,
    description VARCHAR(255),
    -- is_system = TRUE 的群組（admin）不可刪除、權限不可調整，避免管理者把自己鎖在系統外
    is_system   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP    DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 2. 群組被授予的功能
--    feature_key 對應 utils/permission_utils.py 的 FEATURES
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS group_permissions (
    id          SERIAL      PRIMARY KEY,
    group_id    INTEGER     NOT NULL REFERENCES permission_groups(id) ON DELETE CASCADE,
    feature_key VARCHAR(50) NOT NULL,
    -- 側邊欄顯示順序（小的排前面），可於權限管理頁面調整
    sort_order  INTEGER     NOT NULL DEFAULT 0,
    CONSTRAINT _group_feature_uc UNIQUE (group_id, feature_key)
);

CREATE INDEX IF NOT EXISTS ix_group_permissions_group_id
    ON group_permissions (group_id);

-- ------------------------------------------------------------
-- 3. ad_user 增加所屬群組欄位
--    NULL = 尚未開通，登入後只會看到等候畫面
-- ------------------------------------------------------------
ALTER TABLE ad_user
    ADD COLUMN IF NOT EXISTS group_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_ad_user_group_id'
    ) THEN
        ALTER TABLE ad_user
            ADD CONSTRAINT fk_ad_user_group_id
            FOREIGN KEY (group_id) REFERENCES permission_groups(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_ad_user_group_id
    ON ad_user (group_id);

-- ------------------------------------------------------------
-- 4. 建立預設 admin 群組並授予全部功能
-- ------------------------------------------------------------
INSERT INTO permission_groups (name, description, is_system)
VALUES ('admin', '系統管理員，擁有全部功能權限', TRUE)
ON CONFLICT (name) DO NOTHING;

INSERT INTO group_permissions (group_id, feature_key, sort_order)
SELECT g.id, f.feature_key, f.sort_order
FROM permission_groups g
CROSS JOIN (VALUES
    ('batch_sending',   0),
    ('edit_templates',  1),
    ('mailbox_manager', 2),
    ('hpc_contact',     3),
    ('hpc_usage',       4),
    ('setting',         5),
    ('permission',      6)
) AS f(feature_key, sort_order)
WHERE g.name = 'admin'
ON CONFLICT (group_id, feature_key) DO NOTHING;

-- ------------------------------------------------------------
-- 5. 【重要】將現有帳號指派為 admin
--
--    目前 ad_user 只有一個帳號 (chihhsianghsu0410@gmail.com)。
--    若不先設為 admin，權限功能上線後所有人都會被擋在門外，
--    連權限管理頁面都進不去，形成無人可解的死鎖。
--
--    程式啟動時 (init_permission_groups) 也有相同的防呆：
--    偵測到沒有任何 admin 使用者時，會自動把既有帳號設為 admin。
-- ------------------------------------------------------------
--    注意：這裡刻意加上「目前尚無任何 admin 使用者」的條件。
--    若不加，日後不小心重跑這個腳本時，會把所有正在等待審核的新帳號
--    一次全部升級成 admin。
UPDATE ad_user
SET group_id = (SELECT id FROM permission_groups WHERE name = 'admin')
WHERE group_id IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM ad_user u2
      JOIN permission_groups g2 ON u2.group_id = g2.id
      WHERE g2.name = 'admin'
  );

COMMIT;

-- ------------------------------------------------------------
-- 驗證：確認結果符合預期
-- ------------------------------------------------------------
-- SELECT u.id, u.email, g.name AS group_name
-- FROM ad_user u LEFT JOIN permission_groups g ON u.group_id = g.id
-- ORDER BY u.id;
--
-- SELECT g.name, string_agg(p.feature_key, ', ' ORDER BY p.feature_key) AS features
-- FROM permission_groups g
-- LEFT JOIN group_permissions p ON p.group_id = g.id
-- GROUP BY g.name;
