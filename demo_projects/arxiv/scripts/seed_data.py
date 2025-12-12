#!/usr/bin/env python
"""
Seed data script: fetch and upload 10 LLM agent papers for KIE setup.

Usage:
    uv run python scripts/seed_data.py
"""

import sys
sys.path.insert(0, "src")

from arxiv_demo.ingestion import ArxivIngestion


def main():
    print("=" * 60)
    print("Arxiv Demo - Seed Data Setup")
    print("=" * 60)
    print()
    print("This script will:")
    print("  1. Search arxiv for recent LLM agent papers")
    print("  2. Download 10 PDFs")
    print("  3. Upload them to the UC Volume")
    print()

    ingestion = ArxivIngestion()

    # Search for recent LLM agent papers in relevant categories
    print("Searching for papers...")
    papers = ingestion.search_papers(
        query="large language model agents AND (cat:cs.CL OR cat:cs.AI)",
        max_results=10,
    )

    if not papers:
        print("No papers found!")
        return 1

    print(f"\nFound {len(papers)} papers:")
    for i, p in enumerate(papers, 1):
        print(f"  {i}. {p.title[:60]}...")

    print("\nDownloading and uploading to UC Volume...")
    print("(This will take ~30 seconds due to arxiv rate limits)")
    print()

    ingestion.download_and_upload(papers, delay_seconds=3.0)

    print("\n" + "=" * 60)
    print("Seed data setup complete!")
    print("=" * 60)
    print()
    print(f"Uploaded {len(papers)} papers to: {ingestion.config.volume_path}")
    print()
    print("Next steps:")
    print("  1. Go to Databricks UI > AI > Agent Bricks > KIE")
    print("  2. Create a new KIE agent using the UC Volume as source")
    print("  3. Configure the extraction schema")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
