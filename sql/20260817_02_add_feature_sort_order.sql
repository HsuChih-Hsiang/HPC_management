-- ============================================================
-- 權限群組：功能顯示順序 (PostgreSQL)
--
-- 讓每個權限群組可以自訂功能在側邊欄的排列順序。
-- sort_order 由小到大排列，即為該群組成員側邊欄的顯示順序，
-- 第一項同時也是該群組成員登入後的預設落地頁。
--
-- 執行方式：
--   psql -U <user> -d <database> -f sql/20260817_02_add_feature_sort_order.sql
--
-- 若你尚未執行過 20260817_add_permission_tables.sql，
-- 請先執行那一支，再執行本腳本。
--
-- 本腳本可重複執行 (idempotent)。
-- ============================================================

BEGIN;

ALTER TABLE group_permissions
    ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;

-- 既有資料的 sort_order 全是預設值 0，
-- 依照系統預設的功能順序回填，避免側邊欄順序看起來是隨機的。
WITH desired AS (
    SELECT * FROM (VALUES
        ('batch_sending',   0),
        ('edit_templates',  1),
        ('mailbox_manager', 2),
        ('hpc_contact',     3),
        ('hpc_usage',       4),
        ('setting',         5),
        ('permission',      6)
    ) AS t(feature_key, sort_order)
)
UPDATE group_permissions gp
SET sort_order = d.sort_order
FROM desired d
WHERE gp.feature_key = d.feature_key;

COMMIT;

-- ------------------------------------------------------------
-- 驗證
-- ------------------------------------------------------------
-- SELECT g.name,
--        string_agg(p.feature_key, ' > ' ORDER BY p.sort_order, p.id) AS sidebar_order
-- FROM permission_groups g
-- LEFT JOIN group_permissions p ON p.group_id = g.id
-- GROUP BY g.name;
