-- Allow all six levels in existing databases; saved articles stay unchanged.
BEGIN;
ALTER TABLE contents DROP CONSTRAINT contents_check;
ALTER TABLE contents ADD CONSTRAINT contents_check CHECK (
    (mode = 'translate_only' AND target_level IS NULL) OR
    (mode = 'simplify' AND target_level IS NOT NULL AND target_level IN ('A1','A2','B1','B2','C1','C2'))
);
COMMIT;
