"""Operator-applied DDL only. Transactional invalidation also catches raw worker SQL."""

STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE SEQUENCE IF NOT EXISTS archive_memory_revision_seq",
    """CREATE TABLE IF NOT EXISTS archive_memory_versions(
        name text PRIMARY KEY, revision bigint NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS archive_memory_cache(
        key text PRIMARY KEY, revision text NOT NULL, value jsonb NOT NULL,
        expires_at timestamp NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS archive_memory_dirty(
        media_id text PRIMARY KEY, revision bigint NOT NULL,
        queued_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE OR REPLACE FUNCTION archive_memory_invalidate() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      INSERT INTO archive_memory_versions(name,revision) VALUES(TG_TABLE_NAME,1)
      ON CONFLICT(name) DO UPDATE SET revision=archive_memory_versions.revision+1;
      RETURN NULL;
    END $$""",
    """CREATE OR REPLACE FUNCTION archive_memory_enqueue() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      INSERT INTO archive_memory_dirty(media_id,revision)
      VALUES(CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END,
             nextval('archive_memory_revision_seq'))
      ON CONFLICT(media_id) DO UPDATE SET revision=EXCLUDED.revision,
          queued_at=CURRENT_TIMESTAMP;
      RETURN NULL;
    END $$""",
]


def trigger_statements():
    statements = []
    # Each table has its own small revision row. Statement-level triggers avoid
    # writing a revision for each of millions of transcript rows in a bulk insert.
    updates = {
        "media_assets": "filename,synopsis,topics,duration_seconds",
        "transcript_segments": "text,media_id",
        "people": "display_name",
        "person_appearances": "person_id,media_id,speaking_seconds",
        "library_insights": "headline,insights",
    }
    for table, columns in updates.items():
        for suffix, event in [("rows", "INSERT OR DELETE OR TRUNCATE"),
                              ("edit", f"UPDATE OF {columns}")]:
            name = f"archive_memory_{table}_{suffix}"
            # Check catalog before CREATE TRIGGER, no DROP/CREATE on every run.
            statements.append(f"""DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='{name}'
                             AND tgrelid='{table}'::regclass) THEN
                CREATE TRIGGER {name} AFTER {event} ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION archive_memory_invalidate();
              END IF; END $$""")
    for suffix, event in [("rows", "INSERT OR DELETE"),
                          ("edit", "UPDATE OF filename,synopsis,topics")]:
        name = f"archive_memory_enqueue_{suffix}"
        statements.append(f"""DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='{name}'
                         AND tgrelid='media_assets'::regclass) THEN
            CREATE TRIGGER {name} AFTER {event} ON media_assets
            FOR EACH ROW EXECUTE FUNCTION archive_memory_enqueue();
          END IF; END $$""")
    return statements