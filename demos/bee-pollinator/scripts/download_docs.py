"""
Bee Pollinator Demo - Document Download Script

Downloads the 4 key PDF documents for the Knowledge Assistant:
1. Tools for Varroa Management (Honey Bee Health Coalition)
2. USDA Pollinator Priorities Report
3. Supporting Pollinators in Agricultural Landscapes
4. Pollinator-Friendly Plants Guide (NRCS)

Downloads to demos/bee-pollinator/docs/ for upload to Unity Catalog Volume.

Usage:
    python download_docs.py
    python download_docs.py --output-dir /custom/path
"""

import argparse
import sys
from pathlib import Path

import requests


# Document URLs and metadata
DOCUMENTS = [
    {
        "name": "varroa_management_guide.pdf",
        "url": "https://honeybeehealthcoalition.org/wp-content/uploads/2022/08/HBHC-Guide_Varroa-Mgmt_8thEd-082422.pdf",
        "title": "Tools for Varroa Management (8th Edition)",
        "description": "Varroa sampling methods, treatment options, IPM protocols",
    },
    {
        "name": "usda_pollinator_priorities_2022.pdf",
        "url": "https://www.usda.gov/sites/default/files/documents/annual-pollinator-report-2022.pdf",
        "title": "USDA Annual Strategic Pollinator Priorities Report (2022)",
        "description": "Federal pollinator research coordination, IPM strategies, conservation programs",
    },
    {
        "name": "agricultural_landscapes_guide.pdf",
        "url": "https://www.pollinator.org/pollinator.org/assets/generalFiles/Supporting-Pollinators-in-Agricultural-Landscapes_Midwest-Specialty-Crop_August-2025.pdf",
        "title": "Supporting Pollinators in Agricultural Landscapes",
        "description": "IPM strategies, pollinator-friendly practices for specialty crops",
    },
    {
        "name": "pollinator_plants_northeast.pdf",
        "url": "https://www.nrcs.usda.gov/plantmaterials/nypmctn11164.pdf",
        "title": "Pollinator-Friendly Plants for the Northeast United States",
        "description": "Native plant species, bloom times, habitat requirements",
    },
]


def download_file(url: str, output_path: Path) -> bool:
    """Download a file from URL to output path."""
    try:
        print(f"Downloading: {output_path.name}")
        print(f"  From: {url}")

        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()

        # Write in chunks
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        file_size = output_path.stat().st_size / (1024 * 1024)  # MB
        print(f"  → Downloaded: {file_size:.2f} MB")
        return True

    except requests.exceptions.RequestException as e:
        print(f"  ✗ Error downloading: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Download bee pollinator demo documents")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "docs",
        help="Output directory for PDFs (default: demos/bee-pollinator/docs/)",
    )

    args = parser.parse_args()

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {args.output_dir}\n")

    # Download each document
    print("="*60)
    print("DOWNLOADING KNOWLEDGE ASSISTANT DOCUMENTS")
    print("="*60)
    print()

    success_count = 0
    for doc in DOCUMENTS:
        output_path = args.output_dir / doc["name"]

        # Skip if already exists
        if output_path.exists():
            file_size = output_path.stat().st_size / (1024 * 1024)
            print(f"✓ Already exists: {doc['name']} ({file_size:.2f} MB)")
            success_count += 1
            continue

        # Download
        if download_file(doc["url"], output_path):
            success_count += 1

        print()

    # Summary
    print("="*60)
    print("DOWNLOAD COMPLETE")
    print("="*60)
    print(f"\n{success_count}/{len(DOCUMENTS)} documents ready")

    if success_count == len(DOCUMENTS):
        print("\n✓ All documents downloaded successfully!")
        print("\nDocument Summary:")
        for doc in DOCUMENTS:
            print(f"  • {doc['title']}")
            print(f"    {doc['description']}")
            print()

        print("Next steps:")
        print("1. Upload PDFs to Unity Catalog Volume:")
        print(f"   databricks fs cp {args.output_dir}/*.pdf dbfs:/Volumes/your_catalog/bee_health/guidance_docs/")
        print("\n2. Create Knowledge Assistant with these documents:")
        print("   python scripts/setup_agents.py")
    else:
        print("\n⚠ Some downloads failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
