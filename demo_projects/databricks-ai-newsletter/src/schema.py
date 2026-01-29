"""
Data model schema for the newsletter pipeline.
Supports SQLite (local dev) and PostgreSQL/Lakebase (production).
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional, Union, Any
from contextlib import contextmanager

try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


def get_connection(
    db_type: Optional[str] = None,
    db_path: str = "data/newsletter.db",
    pg_host: Optional[str] = None,
    pg_database: Optional[str] = None,
    pg_user: Optional[str] = None,
    pg_password: Optional[str] = None,
    pg_sslmode: str = "require"
) -> Union[sqlite3.Connection, Any]:
    """
    Get database connection (SQLite or PostgreSQL).

    Args:
        db_type: 'sqlite' or 'postgres'. If None, auto-detect from env vars.
        db_path: Path to SQLite database file
        pg_*: PostgreSQL connection params (or use env vars PGHOST, PGDATABASE, DATABASE_URL)

    Environment variables (in order of precedence):
        DATABASE_URL: Full PostgreSQL connection string
        PGHOST, PGDATABASE, PGUSER, PGPASSWORD: Individual connection params

    Returns:
        Database connection object
    """
    # Auto-detect from environment
    if db_type is None:
        db_type = 'postgres' if (os.getenv('DATABASE_URL') or os.getenv('PGHOST')) else 'sqlite'

    if db_type == 'postgres':
        if not POSTGRES_AVAILABLE:
            raise ImportError("psycopg2 not installed. Run: pip install psycopg2-binary")

        # Option 1: Use DATABASE_URL if available
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            from urllib.parse import urlparse, unquote

            parsed = urlparse(database_url)
            pg_host = parsed.hostname
            pg_database = parsed.path.lstrip('/')
            pg_user = unquote(parsed.username) if parsed.username else None
            pg_password = unquote(parsed.password) if parsed.password else None

            # Extract sslmode from query string if present
            if parsed.query and 'sslmode=' in parsed.query:
                import re
                match = re.search(r'sslmode=([^&]+)', parsed.query)
                if match:
                    pg_sslmode = match.group(1)

        # Option 2: Use individual env vars
        else:
            pg_host = pg_host or os.getenv('PGHOST')
            pg_database = pg_database or os.getenv('PGDATABASE', 'databricks_postgres')
            pg_user = pg_user or os.getenv('PGUSER')
            pg_password = pg_password or os.getenv('PGPASSWORD')
            pg_sslmode = pg_sslmode or os.getenv('PGSSLMODE', 'require')

        if not all([pg_host, pg_database, pg_user, pg_password]):
            raise ValueError(
                "PostgreSQL connection requires credentials.\n"
                "Set DATABASE_URL or PGHOST, PGDATABASE, PGUSER, PGPASSWORD\n"
                "See .env.example for details."
            )

        conn = psycopg2.connect(
            host=pg_host,
            database=pg_database,
            user=pg_user,
            password=pg_password,
            sslmode=pg_sslmode
        )
        # Use RealDictCursor for dict-like rows
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn

    else:  # sqlite
        Path(db_path).parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn


def get_db_type(conn: Union[sqlite3.Connection, Any]) -> str:
    """Detect database type from connection object."""
    if isinstance(conn, sqlite3.Connection):
        return 'sqlite'
    elif POSTGRES_AVAILABLE and isinstance(conn, psycopg2.extensions.connection):
        return 'postgres'
    else:
        raise ValueError("Unknown connection type")


def get_placeholder(conn: Union[sqlite3.Connection, Any]) -> str:
    """Get SQL parameter placeholder for this database type."""
    db_type = get_db_type(conn)
    return '?' if db_type == 'sqlite' else '%s'


def execute_query(conn: Union[sqlite3.Connection, Any], sql: str, params: tuple = ()) -> Any:
    """
    Execute SQL query with database-agnostic parameter placeholders.
    Replaces ? with %s for PostgreSQL automatically.
    """
    db_type = get_db_type(conn)

    # Convert ? to %s for PostgreSQL
    if db_type == 'postgres' and '?' in sql:
        # Count placeholders to ensure we don't break LIKE patterns
        sql = sql.replace('?', '%s')

    cursor = conn.cursor()
    cursor.execute(sql, params)
    return cursor


def init_schema(conn: Union[sqlite3.Connection, Any]) -> None:
    """Initialize all tables in the database."""
    db_type = get_db_type(conn)
    cursor = conn.cursor()

    # SQL dialect differences
    if db_type == 'postgres':
        bool_type = 'BOOLEAN'
        timestamp_type = 'TIMESTAMP'
        text_type = 'TEXT'
        now_func = 'CURRENT_TIMESTAMP'
        autoincrement = ''
        on_conflict_ignore = 'ON CONFLICT DO NOTHING'
    else:  # sqlite
        bool_type = 'INTEGER'
        timestamp_type = 'TEXT'
        text_type = 'TEXT'
        now_func = "datetime('now')"
        autoincrement = ''
        on_conflict_ignore = ''

    # Table 1: sources
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS sources (
            source_id {text_type} PRIMARY KEY,
            name {text_type} NOT NULL,
            type {text_type} NOT NULL DEFAULT 'rss',
            url {text_type} NOT NULL,
            enabled {bool_type} NOT NULL DEFAULT {'TRUE' if db_type == 'postgres' else '1'},
            created_at {timestamp_type} NOT NULL DEFAULT {now_func},
            updated_at {timestamp_type} NOT NULL DEFAULT {now_func}
        )
    """)

    # Table 2: feed_items
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS feed_items (
            item_id {text_type} PRIMARY KEY,
            source_id {text_type} NOT NULL,
            guid {text_type},
            title {text_type},
            url {text_type} NOT NULL,
            published_at {timestamp_type},
            raw_json {text_type},
            ingested_at {timestamp_type} NOT NULL DEFAULT {now_func},
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        )
    """)

    # Table 3: page_content
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS page_content (
            item_id {text_type} PRIMARY KEY,
            fetched_at {timestamp_type} NOT NULL DEFAULT {now_func},
            http_status INTEGER,
            final_url {text_type},
            content_text {text_type},
            content_len INTEGER,
            fetch_error {text_type},
            FOREIGN KEY (item_id) REFERENCES feed_items(item_id)
        )
    """)

    # Table 4: kie_outputs
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS kie_outputs (
            item_id {text_type} PRIMARY KEY,
            model_version {text_type},
            created_at {timestamp_type} NOT NULL DEFAULT {now_func},
            kie_json {text_type} NOT NULL,
            FOREIGN KEY (item_id) REFERENCES feed_items(item_id)
        )
    """)

    # Table 5: issues
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS issues (
            issue_id {text_type} PRIMARY KEY,
            week_start {timestamp_type} NOT NULL,
            week_end {timestamp_type} NOT NULL,
            created_at {timestamp_type} NOT NULL DEFAULT {now_func},
            markdown {text_type},
            metadata_json {text_type},
            status {text_type} NOT NULL DEFAULT 'DRAFT'
        )
    """)

    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feed_items_published ON feed_items(published_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feed_items_source ON feed_items(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_issues_week ON issues(week_start, week_end)")

    conn.commit()


def add_default_source(conn: Union[sqlite3.Connection, Any]) -> None:
    """Add the Databricks AWS docs feed as default source."""
    db_type = get_db_type(conn)
    cursor = conn.cursor()

    if db_type == 'postgres':
        cursor.execute("""
            INSERT INTO sources (source_id, name, type, url, enabled)
            VALUES (
                'databricks-aws-docs',
                'Databricks AWS Documentation Updates',
                'rss',
                'https://docs.databricks.com/aws/en/feed.xml',
                TRUE
            )
            ON CONFLICT (source_id) DO NOTHING
        """)
    else:  # sqlite
        cursor.execute("""
            INSERT OR IGNORE INTO sources (source_id, name, type, url, enabled)
            VALUES (
                'databricks-aws-docs',
                'Databricks AWS Documentation Updates',
                'rss',
                'https://docs.databricks.com/aws/en/feed.xml',
                1
            )
        """)

    conn.commit()


if __name__ == "__main__":
    # Demo: initialize database
    print("Detecting database type from environment...")

    conn = get_connection()
    db_type = get_db_type(conn)

    print(f"✓ Connected to {db_type.upper()}")

    if db_type == 'postgres':
        print(f"  Host: {os.getenv('PGHOST')}")
        print(f"  Database: {os.getenv('PGDATABASE')}")
        print(f"  User: {os.getenv('PGUSER')}")

    print("\nInitializing schema...")
    init_schema(conn)
    add_default_source(conn)

    # Verify
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sources")
    rows = cursor.fetchall()

    print("\nSources table:")
    for row in rows:
        if db_type == 'postgres':
            print(f"  - {row['name']}")
        else:
            print(f"  - {dict(row)['name']}")

    conn.close()
    print("\n✅ Database initialized successfully")
