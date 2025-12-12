#!/usr/bin/env python
"""
Backfill metadata for papers already in the UC Volume.

This script:
1. Lists all PDFs in the volume
2. Fetches metadata from arxiv for each paper
3. Saves metadata to the papers Delta table

Usage:
    uv run python scripts/backfill_metadata.py
"""

import sys
import time

sys.path.insert(0, "src")

import arxiv
from arxiv_demo.ingestion import ArxivIngestion, PaperMetadata


def main():
    print("=" * 60)
    print("Backfill Paper Metadata")
    print("=" * 60)
    print()

    ingestion = ArxivIngestion()

    # Get existing files
    files = ingestion.list_uploaded_files()

    if not files:
        print("No files in volume to backfill")
        return 0

    print(f"Found {len(files)} papers in volume")
    print()

    arxiv_client = arxiv.Client()
    success = 0
    failed = 0

    for i, file_path in enumerate(files):
        filename = file_path.split("/")[-1]
        arxiv_id = filename.replace(".pdf", "")

        print(f"[{i+1}/{len(files)}] Fetching metadata for {arxiv_id}...")

        try:
            # Fetch metadata from arxiv
            search = arxiv.Search(id_list=[arxiv_id])
            result = next(arxiv_client.results(search))

            paper = PaperMetadata(
                arxiv_id=arxiv_id,
                title=result.title,
                authors=[author.name for author in result.authors],
                abstract=result.summary,
                published=result.published.isoformat(),
                updated=result.updated.isoformat(),
                categories=result.categories,
                pdf_url=result.pdf_url,
                volume_path=file_path,
            )

            # Save to table
            if ingestion.save_paper_metadata(paper):
                print(f"  ✓ Saved: {paper.title[:50]}...")
                success += 1
            else:
                print(f"  ✗ Failed to save")
                failed += 1

        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed += 1

        # Rate limit for arxiv
        if i < len(files) - 1:
            time.sleep(1)

    print()
    print("=" * 60)
    print(f"Backfill complete: {success} succeeded, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
