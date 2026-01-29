"""
RSS feed ingestion module.
Fetches and parses RSS feeds, storing items idempotently.
"""

import feedparser
import hashlib
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Any as AnyType
from urllib.parse import urlparse

# Import from schema for database-agnostic operations
from schema import execute_query


def generate_item_id(source_id: str, url: str, guid: Optional[str] = None) -> str:
    """
    Generate deterministic item_id from source + url/guid.
    Uses SHA256 to avoid URL length issues.
    """
    unique_key = f"{source_id}::{guid or url}"
    return hashlib.sha256(unique_key.encode()).hexdigest()[:16]


def parse_published_date(entry: feedparser.FeedParserDict) -> Optional[str]:
    """
    Extract published date from feed entry.
    Returns ISO8601 string or None.
    """
    # Try various date fields
    for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
        if hasattr(entry, field) and getattr(entry, field):
            time_struct = getattr(entry, field)
            return datetime(*time_struct[:6]).isoformat()
    return None


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    """Fetch and parse RSS feed."""
    print(f"Fetching feed: {url}")
    feed = feedparser.parse(url)

    if feed.bozo:
        print(f"⚠️  Feed parsing warning: {feed.bozo_exception}")

    return feed


def ingest_feed_items(
    conn,
    source_id: str,
    feed_url: str,
    max_items: Optional[int] = None
) -> Dict[str, Any]:
    """
    Fetch RSS feed and store items idempotently.

    Returns:
        Dict with stats: total_fetched, new_items, updated_items, skipped_items
    """
    feed = fetch_feed(feed_url)
    entries = feed.entries[:max_items] if max_items else feed.entries

    stats = {
        'total_fetched': len(entries),
        'new_items': 0,
        'updated_items': 0,
        'skipped_items': 0,
        'errors': []
    }

    for entry in entries:
        try:
            # Extract basic fields
            guid = getattr(entry, 'id', None) or getattr(entry, 'guid', None)
            title = getattr(entry, 'title', 'No title')
            url = getattr(entry, 'link', None)

            if not url:
                stats['errors'].append(f"No URL for entry: {title}")
                continue

            published_at = parse_published_date(entry)

            # Generate deterministic ID
            item_id = generate_item_id(source_id, url, guid)

            # Store raw entry as JSON for debugging
            raw_json = json.dumps({
                'title': title,
                'link': url,
                'guid': guid,
                'published': published_at,
                'summary': getattr(entry, 'summary', None),
            })

            # Check if item exists
            cursor = execute_query(conn, "SELECT item_id FROM feed_items WHERE item_id = ?", (item_id,))
            existing = cursor.fetchone()

            if existing:
                # Update if changed
                execute_query(conn, """
                    UPDATE feed_items
                    SET title = ?, url = ?, published_at = ?, raw_json = ?
                    WHERE item_id = ?
                """, (title, url, published_at, raw_json, item_id))
                stats['updated_items'] += 1
            else:
                # Insert new item
                execute_query(conn, """
                    INSERT INTO feed_items (item_id, source_id, guid, title, url, published_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (item_id, source_id, guid, title, url, published_at, raw_json))
                stats['new_items'] += 1

        except Exception as e:
            error_msg = f"Error processing entry {getattr(entry, 'title', 'unknown')}: {e}"
            stats['errors'].append(error_msg)
            print(f"❌ {error_msg}")

    conn.commit()
    return stats


def ingest_all_sources(conn, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Ingest all enabled sources.

    Returns:
        List of stats dicts, one per source.
    """
    # Use TRUE for boolean comparison (works in both SQLite and PostgreSQL)
    cursor = execute_query(conn, "SELECT source_id, name, url FROM sources WHERE enabled = TRUE")
    sources = cursor.fetchall()

    results = []
    for source in sources:
        source_id = source['source_id']
        name = source['name']
        url = source['url']

        print(f"\n📥 Ingesting: {name}")
        stats = ingest_feed_items(conn, source_id, url, max_items)
        stats['source_id'] = source_id
        stats['source_name'] = name
        results.append(stats)

        print(f"   ✓ Total: {stats['total_fetched']}, New: {stats['new_items']}, Updated: {stats['updated_items']}")
        if stats['errors']:
            print(f"   ⚠️  Errors: {len(stats['errors'])}")

    return results


if __name__ == "__main__":
    from schema import get_connection, init_schema, add_default_source

    # Initialize DB
    conn = get_connection()
    init_schema(conn)
    add_default_source(conn)

    # Run ingestion
    results = ingest_all_sources(conn, max_items=10)

    # Show summary
    print("\n" + "="*50)
    print("INGESTION SUMMARY")
    print("="*50)
    for result in results:
        print(f"\n{result['source_name']}:")
        print(f"  Fetched: {result['total_fetched']}")
        print(f"  New: {result['new_items']}")
        print(f"  Updated: {result['updated_items']}")

    # Show sample items
    print("\n" + "="*50)
    print("SAMPLE ITEMS")
    print("="*50)
    cursor = conn.execute("""
        SELECT title, url, published_at
        FROM feed_items
        ORDER BY published_at DESC
        LIMIT 5
    """)
    for row in cursor:
        print(f"\n📄 {row['title']}")
        print(f"   🔗 {row['url']}")
        print(f"   📅 {row['published_at']}")

    conn.close()
