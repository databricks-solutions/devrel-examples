"""
Document parsing using Databricks AI functions.

Uses ai_parse_document to extract text content from PDFs.
Structured field extraction is handled by KIE (kie.py).
"""

import json
import time
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from .config import DEFAULT_CONFIG, DatabricksConfig


@dataclass
class ParsedDocument:
    """Parsed document result from ai_parse_document."""

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

    @property
    def tables(self) -> list[dict]:
        """Extract table elements."""
        return [e for e in self.elements if e.get("type") == "table"]

    @property
    def figures(self) -> list[dict]:
        """Extract figure elements."""
        return [e for e in self.elements if e.get("type") == "figure"]

    def summary(self) -> dict:
        """Summary statistics."""
        return {
            "page_count": self.page_count,
            "element_count": len(self.elements),
            "text_blocks": len([e for e in self.elements if e.get("type") == "text"]),
            "tables": len(self.tables),
            "figures": len(self.figures),
        }


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
        """
        Parse a PDF using ai_parse_document.

        Args:
            volume_path: Full path to PDF in UC Volume
            arxiv_id: Arxiv ID for reference

        Returns:
            ParsedDocument with extracted text content
        """
        sql = f"""
        SELECT ai_parse_document(content) as parsed
        FROM read_files('{volume_path}')
        """

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.config.warehouse_id,
            statement=sql,
            wait_timeout="50s",
        )

        # Poll for completion if still running (parsing can take 1-2 minutes)
        max_polls = 24  # 24 * 5s = 2 minutes additional wait
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

        # Parse the JSON result - structure is {"document": {"elements": [...]}}
        raw_result = response.result.data_array[0][0]
        parsed_data = json.loads(raw_result)

        document = parsed_data.get("document", {})
        elements = document.get("elements", [])
        metadata = parsed_data.get("metadata", {})
        page_count = metadata.get("page_count", 0)

        has_tables = any(e.get("type") == "table" for e in elements)
        has_figures = any(e.get("type") == "figure" for e in elements)

        return ParsedDocument(
            arxiv_id=arxiv_id,
            page_count=page_count,
            elements=elements,
            has_tables=has_tables,
            has_figures=has_figures,
        )


def main():
    """Test parsing a document."""
    from .ingestion import ArxivIngestion

    parser = DocumentParser()
    ingestion = ArxivIngestion()
    files = ingestion.list_uploaded_files()

    if not files:
        print("No files in volume to parse")
        return

    file_path = files[0]
    arxiv_id = file_path.split("/")[-1].replace(".pdf", "")

    print(f"Parsing: {file_path}")
    result = parser.parse_document(file_path, arxiv_id)

    print(f"\nParsed document summary:")
    print(json.dumps(result.summary(), indent=2))

    print(f"\nFirst 500 chars of text:")
    print(result.text_content[:500])


if __name__ == "__main__":
    main()
