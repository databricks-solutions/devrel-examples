"""
Key Information Extraction (KIE) module.
TODO: Integrate with Agent Bricks when available.

This is a STUB implementation for local development.
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime

# Import from schema for database-agnostic operations
from schema import execute_query


# KIE JSON schema for reference
KIE_SCHEMA = {
    "source_url": "string",
    "title": "string",
    "published_at": "ISO8601 or empty",
    "product_areas": ["SQL", "Runtime", "Unity Catalog", "MLflow", "Agents", "Admin", "Delta", "Workflows", "Serving", "Other"],
    "change_types": ["new", "improvement", "behavior_change", "deprecation", "bug_fix", "security", "pricing", "other"],
    "who_is_affected": ["admins", "data_engineers", "ml_engineers", "analysts", "app_devs", "platform_engineers", "other"],
    "what_changed": [
        {"claim": "string", "evidence": {"snippet": "<=25 words verbatim from page text"}}
    ],
    "recommended_actions": [
        {"action": "string", "evidence": {"snippet": "<=25 words verbatim from page text"}}
    ],
    "constraints": {
        "uncertainties": ["string"],
        "missing_info": ["string"]
    }
}


def extract_kie_stub(
    item_id: str,
    title: str,
    url: str,
    published_at: Optional[str],
    content_text: str
) -> Dict[str, Any]:
    """
    STUB: Extract key information from page content.

    TODO: Replace with Agent Bricks KIE agent call.

    For now, returns a minimal valid KIE JSON structure.
    """
    # Placeholder implementation
    # Convert published_at to string if it's a datetime object
    published_str = ""
    if published_at:
        if isinstance(published_at, str):
            published_str = published_at
        else:
            published_str = published_at.isoformat() if hasattr(published_at, 'isoformat') else str(published_at)

    kie_output = {
        "source_url": url,
        "title": title,
        "published_at": published_str,
        "product_areas": ["Other"],  # TODO: extract from content
        "change_types": ["other"],    # TODO: extract from content
        "who_is_affected": ["other"], # TODO: extract from content
        "what_changed": [
            {
                "claim": "Content available but not yet analyzed",
                "evidence": {
                    "snippet": content_text[:100].replace('\n', ' ')  # First 100 chars as placeholder
                }
            }
        ],
        "recommended_actions": [],
        "constraints": {
            "uncertainties": ["Full analysis pending Agent Bricks integration"],
            "missing_info": ["Automated KIE extraction not yet implemented"]
        }
    }

    return kie_output


def run_kie_extraction(
    conn,
    item_ids: Optional[List[str]] = None,
    model_version: str = "stub-v1",
    skip_existing: bool = True
) -> Dict[str, Any]:
    """
    Run KIE extraction on items with fetched content.

    Args:
        conn: Database connection
        item_ids: Specific items to process, or None for all
        model_version: Model/agent version identifier
        skip_existing: Skip items that already have KIE output

    Returns:
        Dict with stats: total, processed, skipped, errors
    """
    # Build query
    if item_ids:
        placeholders = ','.join(['?'] * len(item_ids))
        query = f"""
            SELECT fi.item_id, fi.title, fi.url, fi.published_at, pc.content_text
            FROM feed_items fi
            JOIN page_content pc ON fi.item_id = pc.item_id
            LEFT JOIN kie_outputs ko ON fi.item_id = ko.item_id
            WHERE fi.item_id IN ({placeholders})
              AND pc.content_text IS NOT NULL
        """
        if skip_existing:
            query += " AND ko.item_id IS NULL"
        cursor = execute_query(conn, query, tuple(item_ids))
    else:
        query = """
            SELECT fi.item_id, fi.title, fi.url, fi.published_at, pc.content_text
            FROM feed_items fi
            JOIN page_content pc ON fi.item_id = pc.item_id
            LEFT JOIN kie_outputs ko ON fi.item_id = ko.item_id
            WHERE pc.content_text IS NOT NULL
        """
        if skip_existing:
            query += " AND ko.item_id IS NULL"
        cursor = execute_query(conn, query)

    items = cursor.fetchall()

    stats = {
        'total': len(items),
        'processed': 0,
        'skipped': 0,
        'errors': []
    }

    print(f"\n⚠️  Using STUB KIE implementation (Agent Bricks integration pending)")

    for item in items:
        item_id = item['item_id']
        title = item['title']
        url = item['url']
        published_at = item['published_at']
        content_text = item['content_text']

        print(f"\n🔍 Extracting KIE: {title[:60]}...")

        try:
            # TODO: Replace with Agent Bricks API call
            kie_output = extract_kie_stub(item_id, title, url, published_at, content_text)
            kie_json = json.dumps(kie_output, indent=2)

            # Store result
            # Use DELETE + INSERT for compatibility
            execute_query(conn, "DELETE FROM kie_outputs WHERE item_id = ?", (item_id,))
            execute_query(conn, """
                INSERT INTO kie_outputs
                (item_id, model_version, kie_json)
                VALUES (?, ?, ?)
            """, (item_id, model_version, kie_json))
            conn.commit()

            stats['processed'] += 1
            print(f"   ✓ KIE extracted (stub)")

        except Exception as e:
            error_msg = f"KIE error for {item_id}: {e}"
            stats['errors'].append(error_msg)
            print(f"   ❌ {error_msg}")

    return stats


if __name__ == "__main__":
    from schema import get_connection

    conn = get_connection()

    # Run KIE extraction
    print("="*60)
    print("KEY INFORMATION EXTRACTION (STUB)")
    print("="*60)

    stats = run_kie_extraction(conn, skip_existing=True)

    print("\n" + "="*60)
    print("KIE SUMMARY")
    print("="*60)
    print(f"Total items: {stats['total']}")
    print(f"Processed: {stats['processed']}")
    print(f"Skipped: {stats['skipped']}")
    if stats['errors']:
        print(f"Errors: {len(stats['errors'])}")

    # Show sample KIE output
    print("\n" + "="*60)
    print("SAMPLE KIE OUTPUT")
    print("="*60)
    cursor = conn.execute("""
        SELECT fi.title, ko.kie_json
        FROM feed_items fi
        JOIN kie_outputs ko ON fi.item_id = ko.item_id
        LIMIT 1
    """)
    row = cursor.fetchone()
    if row:
        print(f"\n📄 {row['title']}\n")
        kie_data = json.loads(row['kie_json'])
        print(json.dumps(kie_data, indent=2))

    conn.close()
