"""
Chat client for interacting with the Knowledge Assistant agent.
"""

from collections.abc import Iterator

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from .config import DEFAULT_CONFIG, DatabricksConfig


class ChatClient:
    """Client for chatting with the Knowledge Assistant agent."""

    def __init__(
        self,
        endpoint_name: str | None = None,
        config: DatabricksConfig | None = None,
    ):
        self.config = config or DEFAULT_CONFIG
        self.endpoint_name = endpoint_name or self.config.ka_endpoint
        self._client: WorkspaceClient | None = None

    @property
    def client(self) -> WorkspaceClient:
        if self._client is None:
            self._client = WorkspaceClient(profile=self.config.profile)
        return self._client

    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        """
        Stream chat response from the agent.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                      e.g. [{'role': 'user', 'content': 'hello'}]
        
        Yields:
            Chunks of response text.
        """
        if not self.endpoint_name:
            raise ValueError("Knowledge Assistant endpoint not configured. Set KA_ENDPOINT env var.")

        # Convert simple dicts to SDK ChatMessage objects
        sdk_messages = []
        for msg in messages:
            role = ChatMessageRole.USER if msg["role"] == "user" else ChatMessageRole.SYSTEM if msg["role"] == "system" else ChatMessageRole.ASSISTANT
            sdk_messages.append(ChatMessage(role=role, content=msg["content"]))

        # Query endpoint with streaming
        response = self.client.serving_endpoints.query(
            name=self.endpoint_name,
            messages=sdk_messages,
            stream=True,
        )

        # Iterate over streaming response
        # The SDK returns an iterator of ChatCompletionChunk when stream=True
        # We need to extract the delta content
        for chunk in response:
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
