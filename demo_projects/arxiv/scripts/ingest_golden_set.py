#!/usr/bin/env python
"""
Ingest "Golden Set" papers for evaluation context.
Includes: ReAct, Reflexion, Tool Learning, Plan-and-Solve, Voyager.
"""

import sys
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, "src")

import arxiv
from arxiv_demo.ingestion import ArxivIngestion, PaperMetadata

# Seminal Agent Papers
GOLDEN_SET_IDS = [
    "2210.03629",  # ReAct: Synergizing Reasoning and Acting in Language Models
    "2303.11366",  # Reflexion: Language Agents with Verbal Reinforcement Learning
    "2305.04091",  # Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning by Large Language Models
    "2304.08354",  # Tool Learning with Foundation Models
    "2305.16291",  # Voyager: An Open-Ended Embodied Agent with Large Language Models
]

def main():
    print(f"Preparing to ingest {len(GOLDEN_SET_IDS)} golden set papers...")
    
    # Use config from env
    ingestion = ArxivIngestion()
    
    # Check what we already have (to avoid re-downloading if possible, though download_and_upload handles overwrite)
    # We'll just fetch fresh metadata to be safe
    
    client = arxiv.Client()
    search = arxiv.Search(id_list=GOLDEN_SET_IDS)
    
    papers_to_ingest = []
    found_ids = set()
    
    print("Fetching metadata from Arxiv...")
    for result in client.results(search):
        paper_id = result.entry_id.split("/")[-1].split("v")[0] # clean version if needed, but usually matches
        found_ids.add(paper_id)
        
        # Handle version suffix in ID if present in search result vs input
        # Arxiv API usually returns 2210.03629v3. We want to match broadly.
        
        p = PaperMetadata(
            arxiv_id=result.entry_id.split("/")[-1],
            title=result.title,
            authors=[a.name for a in result.authors],
            abstract=result.summary,
            published=result.published.isoformat(),
            updated=result.updated.isoformat(),
            categories=result.categories,
            pdf_url=result.pdf_url
        )
        papers_to_ingest.append(p)
        print(f"  Found: {p.arxiv_id} - {p.title}")

    if not papers_to_ingest:
        print("No papers found. Check IDs.")
        return

    print(f"\nDownloading and uploading {len(papers_to_ingest)} papers...")
    ingestion.download_and_upload(papers_to_ingest, delay_seconds=10.0)
    
    print("\nGolden set ingestion complete.")

if __name__ == "__main__":
    main()
