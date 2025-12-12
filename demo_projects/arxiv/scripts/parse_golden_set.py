"""
Script to parse all PDFs in the volume and populate the parsed_documents table.
Needed for KIE to work on the Golden Set.
"""

from arxiv_demo.ingestion import ArxivIngestion
from arxiv_demo.parsing import DocumentParser
import time

def main():
    print("Initializing parser...")
    ingestion = ArxivIngestion()
    parser = DocumentParser()
    
    # List all files in volume
    files = ingestion.list_uploaded_files()
    pdf_files = [f for f in files if f.endswith(".pdf")]
    
    print(f"Found {len(pdf_files)} PDFs in volume.")
    
    for i, file_path in enumerate(pdf_files):
        arxiv_id = file_path.split("/")[-1].replace(".pdf", "")
        print(f"[{i+1}/{len(pdf_files)}] Parsing {arxiv_id}...")
        
        try:
            # Parse
            doc = parser.parse_document(file_path, arxiv_id)
            print(f"  Parsed {doc.page_count} pages.")
            
            # Save
            if parser.save_parsed_document(doc):
                print("  Saved to parsed_documents table.")
            else:
                print("  Failed to save to table.")
                
        except Exception as e:
            print(f"  Error processing {arxiv_id}: {e}")
            
    print("\nParsing complete!")

if __name__ == "__main__":
    main()
