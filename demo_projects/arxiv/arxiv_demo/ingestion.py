"""
Arxiv paper ingestion, parsing, and extraction.

Handles the full pipeline:
- Search arxiv for papers
- Download PDFs and upload to Databricks UC Volume
- Parse PDFs with ai_parse_document
- Extract structured fields with KIE agent
"""

import io
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import arxiv
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from databricks.sdk.service.sql import StatementState

from .config import DEFAULT_CONFIG, DatabricksConfig


# =============================================================================
# Data Classes
# =============================================================================

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
        return asdict(self)


@dataclass
class ParsedDocument:
    """Result from ai_parse_document."""
    arxiv_id: str
    page_count: int
    elements: list[dict]
    has_tables: bool
    has_figures: bool

    @property
    def text_content(self) -> str:
        """Extract all text content."""
        texts = []
        for elem in self.elements:
            if elem.get("type") == "text":
                texts.append(elem.get("content", ""))
        return "\n\n".join(texts)


@dataclass
class ExtractedPaper:
    """Structured fields extracted by KIE agent."""
    title: str
    authors: list[str]
    affiliation: str
    contributions: list[str]
    methodology: str
    limitations: list[str]
    topics: list[str]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "affiliation": self.affiliation,
            "contributions": self.contributions,
            "methodology": self.methodology,
            "limitations": self.limitations,
            "topics": self.topics,
        }


# =============================================================================
# Arxiv Ingestion
# =============================================================================

class ArxivIngestion:
    """Handle arxiv paper search, download, and upload to Databricks."""

    def __init__(self, config: DatabricksConfig | None = None):
        self.config = config or DEFAULT_CONFIG
        self._client: WorkspaceClient | None = None

    @property
    def client(self) -> WorkspaceClient:
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
        """Search arxiv for papers matching query."""
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
        return papers

    def download_and_upload(
        self,
        papers: list[PaperMetadata],
        delay_seconds: float = 3.0,
    ) -> list[PaperMetadata]:
        """Download PDFs from arxiv and upload to UC Volume."""
        client = arxiv.Client()

        for i, paper in enumerate(papers):
            # Download PDF
            search = arxiv.Search(id_list=[paper.arxiv_id])
            result = next(client.results(search))
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

            # Save metadata to Delta table
            self.save_paper_metadata(paper)

            # Rate limit
            if i < len(papers) - 1:
                time.sleep(delay_seconds)

        return papers

    def list_uploaded_files(self) -> list[str]:
        """List files in the UC Volume."""
        try:
            files = self.client.files.list_directory_contents(self.config.volume_path)
            return [f.path for f in files]
        except Exception:
            return []

    def delete_file(self, volume_path: str) -> bool:
        """Delete a file from the UC Volume."""
        try:
            self.client.files.delete(volume_path)
            return True
        except Exception:
            return False

    def save_paper_metadata(self, paper: PaperMetadata) -> bool:
        """Save paper metadata to the papers Delta table."""
        title_escaped = paper.title.replace("'", "''")
        abstract_escaped = paper.abstract.replace("'", "''")
        authors_sql = ", ".join([f"'{a.replace(chr(39), chr(39)+chr(39))}'" for a in paper.authors])
        categories_sql = ", ".join([f"'{c}'" for c in paper.categories])

        delete_sql = f"DELETE FROM {self.config.full_schema}.papers WHERE arxiv_id = '{paper.arxiv_id}'"
        insert_sql = f"""
        INSERT INTO {self.config.full_schema}.papers (
            arxiv_id, title, authors, abstract, published_date, updated_date,
            categories, pdf_url, volume_path, in_knowledge_assistant, ingested_at
        ) VALUES (
            '{paper.arxiv_id}', '{title_escaped}', ARRAY({authors_sql}), '{abstract_escaped}',
            TIMESTAMP'{paper.published}', TIMESTAMP'{paper.updated}',
            ARRAY({categories_sql}), '{paper.pdf_url}', '{paper.volume_path}',
            TRUE, CURRENT_TIMESTAMP()
        )
        """

        try:
            self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id, statement=delete_sql, wait_timeout="30s"
            )
            self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id, statement=insert_sql, wait_timeout="30s"
            )
            return True
        except Exception:
            return False

    def get_all_papers(self) -> list[dict]:
        """Get all papers from the papers Delta table."""
        sql = f"""
        SELECT arxiv_id, title, authors, abstract, published_date, categories, pdf_url, volume_path
        FROM {self.config.full_schema}.papers ORDER BY published_date DESC
        """
        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id, statement=sql, wait_timeout="30s"
            )
            if not response.result or not response.result.data_array:
                return []
            columns = [col.name for col in response.manifest.schema.columns]
            return [{columns[i]: row[i] for i in range(len(columns))} for row in response.result.data_array]
        except Exception:
            return []

    def delete_paper(self, arxiv_id: str) -> bool:
        """Delete a paper from both the volume and the papers table."""
        sql = f"DELETE FROM {self.config.full_schema}.papers WHERE arxiv_id = '{arxiv_id}'"
        try:
            self.client.statement_execution.execute_statement(
                warehouse_id=self.config.warehouse_id, statement=sql, wait_timeout="30s"
            )
        except Exception:
            pass
        filename = f"{arxiv_id.replace('/', '_')}.pdf"
        volume_path = f"{self.config.volume_path}/{filename}"
        return self.delete_file(volume_path)


# =============================================================================
# Document Parser (ai_parse_document)
# =============================================================================

class DocumentParser:
    """Parse documents using ai_parse_document SQL function."""

    def __init__(self, config: DatabricksConfig | None = None):
        self.config = config or DEFAULT_CONFIG
        self._client: WorkspaceClient | None = None

    @property
    def client(self) -> WorkspaceClient:
        if self._client is None:
            self._client = WorkspaceClient(profile=self.config.profile)
        return self._client

    def parse_document(self, volume_path: str, arxiv_id: str) -> ParsedDocument:
        """Parse a PDF using ai_parse_document."""
        sql = f"SELECT ai_parse_document(content) as parsed FROM read_files('{volume_path}')"

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.config.warehouse_id, statement=sql, wait_timeout="50s"
        )

        # Poll for completion (parsing can take 1-2 minutes)
        max_polls = 24
        poll_count = 0
        while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if poll_count >= max_polls:
                raise RuntimeError(f"Parse timed out after {50 + poll_count * 5}s")
            time.sleep(5)
            response = self.client.statement_execution.get_statement(response.statement_id)
            poll_count += 1

        if response.status.state == StatementState.FAILED:
            raise RuntimeError(f"Parse failed: {response.status.error}")
        if response.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"Unexpected state: {response.status.state}")
        if not response.result or not response.result.data_array:
            raise RuntimeError("No result returned from ai_parse_document")

        raw_result = response.result.data_array[0][0]
        parsed_data = json.loads(raw_result)
        document = parsed_data.get("document", {})
        elements = document.get("elements", [])
        metadata = parsed_data.get("metadata", {})

        return ParsedDocument(
            arxiv_id=arxiv_id,
            page_count=metadata.get("page_count", 0),
            elements=elements,
            has_tables=any(e.get("type") == "table" for e in elements),
            has_figures=any(e.get("type") == "figure" for e in elements),
        )


# =============================================================================
# KIE Client (Knowledge Information Extraction)
# =============================================================================

class KIEClient:
    """Client for querying the KIE Agent Brick."""

    def __init__(self, endpoint_name: str | None = None, config: DatabricksConfig | None = None):
        self.config = config or DEFAULT_CONFIG
        self.endpoint_name = endpoint_name or self.config.kie_endpoint
        self._client: WorkspaceClient | None = None

    @property
    def client(self) -> WorkspaceClient:
        if self._client is None:
            self._client = WorkspaceClient(profile=self.config.profile)
        return self._client

    def extract_from_text(self, text_content: str, arxiv_id: str = "") -> ExtractedPaper:
        """Extract structured fields from parsed text content.

        Uses the OpenAI-compatible client for Agent Brick endpoints,
        which handles OAuth token exchange automatically for both
        local development and Databricks Apps deployment.
        """
        text = text_content[:50000] if len(text_content) > 50000 else text_content

        # Use OpenAI-compatible client for Agent Brick endpoints
        openai_client = self.client.serving_endpoints.get_open_ai_client()

        response = openai_client.chat.completions.create(
            model=self.endpoint_name,
            messages=[
                {
                    "role": "user",
                    "content": f"Extract information from this research paper:\n\n{text}",
                }
            ],
        )

        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                raise ValueError(f"Could not parse KIE response as JSON: {content[:500]}")
        else:
            raise ValueError(f"Unexpected response format: {response}")

        return ExtractedPaper(
            title=data.get("title", ""),
            authors=data.get("authors", []),
            affiliation=data.get("affiliation", ""),
            contributions=data.get("contributions", []),
            methodology=data.get("methodology", ""),
            limitations=data.get("limitations", []),
            topics=data.get("topics", []),
        )
