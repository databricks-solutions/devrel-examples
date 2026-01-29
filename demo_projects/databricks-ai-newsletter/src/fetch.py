"""
Page content fetching module.
Fetches URLs from feed_items and extracts text content.
"""

import requests
import time
from typing import Dict, Any, Optional, List
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Import from schema for database-agnostic operations
from schema import execute_query


def extract_text_content(html: str, url: str) -> str:
    """
    Extract clean text content from HTML.
    Removes navigation, scripts, styles, etc.
    """
    soup = BeautifulSoup(html, 'lxml')

    # Remove unwanted elements
    for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
        element.decompose()

    # Try to find main content area
    # Common patterns for docs sites
    main_content = (
        soup.find('main') or
        soup.find('article') or
        soup.find('div', class_=['content', 'main-content', 'article', 'post']) or
        soup.find('body')
    )

    if main_content:
        text = main_content.get_text(separator='\n', strip=True)
    else:
        text = soup.get_text(separator='\n', strip=True)

    # Clean up whitespace
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines)


def fetch_page_content(
    url: str,
    timeout: int = 30,
    max_content_len: int = 100_000
) -> Dict[str, Any]:
    """
    Fetch and extract content from a URL.

    Returns:
        Dict with: http_status, final_url, content_text, content_len, fetch_error
    """
    result = {
        'http_status': None,
        'final_url': url,
        'content_text': None,
        'content_len': 0,
        'fetch_error': None
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; DatabricksNewsletterBot/1.0)'
        }

        response = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
        result['http_status'] = response.status_code
        result['final_url'] = response.url

        if response.status_code != 200:
            result['fetch_error'] = f"HTTP {response.status_code}"
            return result

        # Extract text content
        content_text = extract_text_content(response.text, url)

        # Truncate if needed
        if len(content_text) > max_content_len:
            content_text = content_text[:max_content_len] + "\n\n[TRUNCATED]"

        result['content_text'] = content_text
        result['content_len'] = len(content_text)

    except requests.Timeout:
        result['fetch_error'] = "Timeout"
    except requests.RequestException as e:
        result['fetch_error'] = f"Request error: {str(e)[:200]}"
    except Exception as e:
        result['fetch_error'] = f"Parse error: {str(e)[:200]}"

    return result


def fetch_items_content(
    conn,
    item_ids: Optional[List[str]] = None,
    skip_existing: bool = True,
    delay: float = 0.5
) -> Dict[str, Any]:
    """
    Fetch page content for feed items.

    Args:
        conn: Database connection
        item_ids: List of specific item IDs to fetch, or None for all
        skip_existing: Skip items that already have content
        delay: Delay between requests (seconds)

    Returns:
        Dict with stats: total, fetched, skipped, errors
    """
    # Build query
    if item_ids:
        placeholders = ','.join(['?'] * len(item_ids))
        query = f"""
            SELECT fi.item_id, fi.url, fi.title
            FROM feed_items fi
            LEFT JOIN page_content pc ON fi.item_id = pc.item_id
            WHERE fi.item_id IN ({placeholders})
        """
        if skip_existing:
            query += " AND pc.item_id IS NULL"
        cursor = execute_query(conn, query, tuple(item_ids))
    else:
        query = """
            SELECT fi.item_id, fi.url, fi.title
            FROM feed_items fi
            LEFT JOIN page_content pc ON fi.item_id = pc.item_id
        """
        if skip_existing:
            query += " WHERE pc.item_id IS NULL"
        cursor = execute_query(conn, query)

    items = cursor.fetchall()

    stats = {
        'total': len(items),
        'fetched': 0,
        'failed': 0,
        'errors': []
    }

    for item in items:
        item_id = item['item_id']
        url = item['url']
        title = item['title']

        print(f"🌐 Fetching: {title[:60]}...")

        # Fetch content
        result = fetch_page_content(url)

        # Store in database
        try:
            # PostgreSQL uses INSERT ... ON CONFLICT, SQLite uses INSERT OR REPLACE
            # Use DELETE + INSERT for compatibility
            execute_query(conn, "DELETE FROM page_content WHERE item_id = ?", (item_id,))
            execute_query(conn, """
                INSERT INTO page_content
                (item_id, http_status, final_url, content_text, content_len, fetch_error)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item_id,
                result['http_status'],
                result['final_url'],
                result['content_text'],
                result['content_len'],
                result['fetch_error']
            ))
            conn.commit()

            if result['fetch_error']:
                stats['failed'] += 1
                print(f"   ❌ {result['fetch_error']}")
            else:
                stats['fetched'] += 1
                print(f"   ✓ {result['content_len']:,} chars")

        except Exception as e:
            error_msg = f"DB error for {item_id}: {e}"
            stats['errors'].append(error_msg)
            print(f"   ❌ {error_msg}")

        # Rate limiting
        time.sleep(delay)

    return stats


if __name__ == "__main__":
    from schema import get_connection

    conn = get_connection()

    # Fetch content for all items without content
    print("="*60)
    print("FETCHING PAGE CONTENT")
    print("="*60)

    stats = fetch_items_content(conn, skip_existing=True, delay=1.0)

    print("\n" + "="*60)
    print("FETCH SUMMARY")
    print("="*60)
    print(f"Total items: {stats['total']}")
    print(f"Successfully fetched: {stats['fetched']}")
    print(f"Failed: {stats['failed']}")
    if stats['errors']:
        print(f"Errors: {len(stats['errors'])}")

    # Show sample content
    print("\n" + "="*60)
    print("SAMPLE CONTENT")
    print("="*60)
    cursor = conn.execute("""
        SELECT fi.title, pc.content_len, pc.http_status, pc.fetch_error
        FROM feed_items fi
        JOIN page_content pc ON fi.item_id = pc.item_id
        ORDER BY fi.published_at DESC
        LIMIT 5
    """)
    for row in cursor:
        print(f"\n📄 {row['title']}")
        if row['fetch_error']:
            print(f"   ❌ Error: {row['fetch_error']}")
        else:
            print(f"   ✓ {row['content_len']:,} chars (HTTP {row['http_status']})")

    conn.close()
