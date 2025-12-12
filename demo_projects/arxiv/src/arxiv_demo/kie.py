"""
Knowledge Information Extraction (KIE) Agent client.

Queries the KIE Agent Brick to extract structured fields from papers.
"""

import json
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from .config import DEFAULT_CONFIG, DatabricksConfig


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


class KIEClient:
    """Client for querying the KIE Agent Brick."""

    def __init__(
        self,
        endpoint_name: str | None = None,
        config: DatabricksConfig | None = None,
    ):
        self.config = config or DEFAULT_CONFIG
        self.endpoint_name = endpoint_name or self.config.kie_endpoint
        self._client: WorkspaceClient | None = None

    @property
    def client(self) -> WorkspaceClient:
        if self._client is None:
            self._client = WorkspaceClient(profile=self.config.profile)
        return self._client

    def extract_from_text(self, text_content: str, arxiv_id: str = "") -> ExtractedPaper:
        """
        Extract structured fields from parsed text content.

        Args:
            text_content: Text content from ai_parse_document
            arxiv_id: Optional arxiv ID for logging

        Returns:
            ExtractedPaper with structured fields
        """
        # Truncate if too long (endpoint limits)
        text = text_content[:50000] if len(text_content) > 50000 else text_content

        response = self.client.serving_endpoints.query(
            name=self.endpoint_name,
            messages=[
                ChatMessage(
                    role=ChatMessageRole.USER,
                    content=f"Extract information from this research paper:\n\n{text}",
                )
            ],
        )

        # Parse the response - KIE returns structured JSON
        if hasattr(response, "choices") and response.choices:
            content = response.choices[0].message.content
            # The content should be JSON
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

    def extract_batch(
        self, texts: list[tuple[str, str]], on_progress=None
    ) -> dict[str, ExtractedPaper | None]:
        """
        Extract fields from multiple papers.

        Args:
            texts: List of (arxiv_id, text_content) tuples
            on_progress: Optional callback(current, total, arxiv_id)

        Returns:
            Dict mapping arxiv_id to ExtractedPaper (or None on error)
        """
        results = {}

        for i, (arxiv_id, text_content) in enumerate(texts):
            if on_progress:
                on_progress(i, len(texts), arxiv_id)

            try:
                results[arxiv_id] = self.extract_from_text(text_content, arxiv_id)
            except Exception as e:
                print(f"KIE extraction failed for {arxiv_id}: {e}")
                results[arxiv_id] = None

        return results


def main():
    """Test KIE extraction."""
    from .ingestion import ArxivIngestion
    from .parsing import DocumentParser

    # Get a file from the volume
    ingestion = ArxivIngestion()
    files = ingestion.list_uploaded_files()

    if not files:
        print("No files in volume")
        return

    file_path = files[0]
    arxiv_id = file_path.split("/")[-1].replace(".pdf", "")

    print(f"Testing KIE extraction on: {file_path}")

    # First parse the PDF to get text
    print("Step 1: Parsing PDF with ai_parse_document...")
    parser = DocumentParser()
    parsed_doc = parser.parse_document(file_path, arxiv_id)
    print(f"  Extracted {len(parsed_doc.text_content)} chars of text")

    # Then run KIE on the text
    print("Step 2: Running KIE extraction...")
    kie = KIEClient()
    result = kie.extract_from_text(parsed_doc.text_content, arxiv_id)

    print("\nExtracted fields:")
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
