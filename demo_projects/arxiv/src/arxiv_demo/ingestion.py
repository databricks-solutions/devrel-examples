"""
Arxiv paper ingestion: search, download, and upload to Databricks UC Volume.

Usage:
    from arxiv_demo.ingestion import ArxivIngestion

    ingestion = ArxivIngestion()
    papers = ingestion.search_papers("LLM agents", max_results=10)
    ingestion.download_and_upload(papers)
"""

import io
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import arxiv
from databricks.sdk import WorkspaceClient

from .config import DEFAULT_CONFIG, DatabricksConfig


@dataclass
class PaperMetadata:
    """Metadata for an arxiv paper."""

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    categories: list[str]
    pdf_url: str
    volume_path: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)


class ArxivIngestion:
    """Handle arxiv paper search, download, and upload to Databricks."""

    def __init__(self, config: DatabricksConfig | None = None):
        self.config = config or DEFAULT_CONFIG
        self._client: WorkspaceClient | None = None

    @property
    def client(self) -> WorkspaceClient:
        """Lazy-load Databricks client."""
        if self._client is None:
            self._client = WorkspaceClient(profile=self.config.profile)
        return self._client

    def search_papers(
        self,
        query: str,
        max_results: int = 10,
        sort_by: arxiv.SortCriterion = arxiv.SortCriterion.SubmittedDate,
        sort_order: arxiv.SortOrder = arxiv.SortOrder.Descending,
    ) -> list[PaperMetadata]:
        """
        Search arxiv for papers matching query.

        Args:
            query: Search query (e.g., "LLM agents", "cat:cs.AI AND transformer")
            max_results: Maximum number of results to return
            sort_by: Sort criterion (default: submission date)
            sort_order: Sort order (default: descending/newest first)

        Returns:
            List of PaperMetadata objects
        """
        print(f"Searching arxiv for: {query}")

        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        papers = []
        for result in client.results(search):
            paper = PaperMetadata(
                arxiv_id=result.entry_id.split("/")[-1],
                title=result.title,
                authors=[author.name for author in result.authors],
                abstract=result.summary,
                published=result.published.isoformat(),
                updated=result.updated.isoformat(),
                categories=result.categories,
                pdf_url=result.pdf_url,
            )
            papers.append(paper)
            print(f"  Found: {paper.arxiv_id} - {paper.title[:60]}...")

        print(f"Found {len(papers)} papers")
        return papers

    def download_and_upload(
        self,
        papers: list[PaperMetadata],
        delay_seconds: float = 3.0,
    ) -> list[PaperMetadata]:
        """
        Download PDFs from arxiv and upload to UC Volume.

        Args:
            papers: List of papers to download
            delay_seconds: Delay between downloads (arxiv rate limit)

        Returns:
            List of papers with volume_path set
        """
        client = arxiv.Client()

        for i, paper in enumerate(papers):
            print(f"[{i + 1}/{len(papers)}] Downloading: {paper.arxiv_id}")

            # Download PDF
            search = arxiv.Search(id_list=[paper.arxiv_id])
            result = next(client.results(search))

            # Download to temp file
            result.download_pdf(dirpath=".", filename="_temp.pdf")

            # Read and upload
            temp_path = Path("_temp.pdf")
            pdf_content = temp_path.read_bytes()
            temp_path.unlink()

            # Upload to UC Volume
            filename = f"{paper.arxiv_id.replace('/', '_')}.pdf"
            volume_file_path = f"{self.config.volume_path}/{filename}"

            self.client.files.upload(
                file_path=volume_file_path,
                contents=io.BytesIO(pdf_content),
                overwrite=True,
            )

            paper.volume_path = volume_file_path
            print(f"  Uploaded: {volume_file_path}")

            # Save metadata to Delta table
            if self.save_paper_metadata(paper):
                print(f"  Saved metadata to papers table")

            # Rate limit
            if i < len(papers) - 1:
                time.sleep(delay_seconds)

        print(f"\nUploaded {len(papers)} PDFs to {self.config.volume_path}")
        return papers

    def list_uploaded_files(self) -> list[str]:
        """List files in the UC Volume."""
        try:
            files = self.client.files.list_directory_contents(self.config.volume_path)
            return [f.path for f in files]
        except Exception as e:
            print(f"Error listing files: {e}")
            return []

    def delete_file(self, volume_path: str) -> bool:
        """Delete a file from the UC Volume."""
        try:
            self.client.files.delete(volume_path)
            print(f"Deleted: {volume_path}")
            return True
        except Exception as e:
            print(f"Error deleting {volume_path}: {e}")
            return False

    def save_paper_metadata(self, paper: PaperMetadata) -> bool:
        """
        Save paper metadata to the papers Delta table.

        Uses MERGE to upsert - update if exists, insert if new.
        """
        # Escape single quotes in text fields
        title_escaped = paper.title.replace("'", "''")
        abstract_escaped = paper.abstract.replace("'", "''")
        authors_sql = ", ".join([f"'{a.replace(chr(39), chr(39)+chr(39))}'" for a in paper.authors])
        categories_sql = ", ".join([f"'{c}'" for c in paper.categories])

        # Simple delete and insert pattern
        delete_sql = f"DELETE FROM {self.config.full_schema}.papers WHERE arxiv_id = '{paper.arxiv_id}'"
        
        insert_sql = f"""
        INSERT INTO {self.config.full_schema}.papers (
            arxiv_id, title, authors, abstract, published_date, updated_date,
            categories, pdf_url, volume_path, in_knowledge_assistant, ingested_at
        ) VALUES (
            '{paper.arxiv_id}',
            '{title_escaped}',
            ARRAY({authors_sql}),
            '{abstract_escaped}',
            TIMESTAMP'{paper.published}',
            TIMESTAMP'{paper.updated}',
            ARRAY({categories_sql}),
            '{paper.pdf_url}',
            '{paper.volume_path}',
            TRUE,
            CURRENT_TIMESTAMP()
        )
        """

        try:
            # First delete existing (if any)
            self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id,
                statement=delete_sql,
                wait_timeout="30s",
            )
            
            # Then insert new
            self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id,
                statement=insert_sql,
                wait_timeout="30s",
            )
            return True
        except Exception as e:
            print(f"Error saving metadata for {paper.arxiv_id}: {e}")
            return False

    def get_all_papers(self) -> list[dict]:
        """
        Get all papers from the papers Delta table.

        Returns:
            List of dicts with paper metadata
        """
        sql = f"""
        SELECT arxiv_id, title, authors, abstract, published_date,
               categories, pdf_url, volume_path
        FROM {self.config.full_schema}.papers
        ORDER BY published_date DESC
        """

        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id,
                statement=sql,
                wait_timeout="30s",
            )

            if not response.result or not response.result.data_array:
                return []

            # Map column names to indices
            columns = [col.name for col in response.manifest.schema.columns]

            papers = []
            for row in response.result.data_array:
                paper = {columns[i]: row[i] for i in range(len(columns))}
                papers.append(paper)

            return papers
        except Exception as e:
            print(f"Error fetching papers: {e}")
            return []

    def delete_paper(self, arxiv_id: str) -> bool:
        """Delete a paper from both the volume and the papers table."""
        # Delete from table
        sql = f"DELETE FROM {self.config.full_schema}.papers WHERE arxiv_id = '{arxiv_id}'"
        try:
            self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id,
                statement=sql,
                wait_timeout="30s",
            )
        except Exception as e:
            print(f"Error deleting from table: {e}")

        # Delete file from volume
        filename = f"{arxiv_id.replace('/', '_')}.pdf"
        volume_path = f"{self.config.volume_path}/{filename}"
        return self.delete_file(volume_path)


def main():
    """Example usage."""
    ingestion = ArxivIngestion()

    papers = ingestion.search_papers(
        query="LLM agents",
        max_results=3,
    )

    if papers:
        ingestion.download_and_upload(papers)
        print(f"\nFiles in volume:")
        for f in ingestion.list_uploaded_files():
            print(f"  {f}")


if __name__ == "__main__":
    main()
