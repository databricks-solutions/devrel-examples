# Setting Up Knowledge Assistant

This guide walks through creating a Knowledge Assistant agent to query your arxiv papers.

## Prerequisites

- Papers uploaded to UC Volume at `/Volumes/arxiv_demo/main/pdfs/`
- Workspace in us-west-2 or us-east-1 (required for Agent Bricks)

## Step 1: Navigate to Agents

1. In your Databricks workspace, click **Agents** in the left sidebar
2. Find the **Knowledge Assistant** tile
3. Click **Build**

## Step 2: Configure Knowledge Source

1. **Name your agent**: `arxiv-papers` (or similar)
2. **Add knowledge source**:
   - Click "Add knowledge source"
   - Select **Unity Catalog files**
   - Navigate to: `arxiv_demo` > `main` > `pdfs`
   - Select the volume
3. Click **Continue**

## Step 3: Configure Agent Settings

Default settings should work for most cases:
- **Model**: Leave default (typically Claude or GPT-4)
- **System prompt**: Can customize later if needed

Click **Create** to deploy the agent.

## Step 4: Test in AI Playground

Once deployed (may take a few minutes for indexing):

1. The agent will open in AI Playground
2. Try asking questions like:
   - "What papers discuss LLM agents?"
   - "Summarize the main contributions of these papers"
   - "What evaluation methods are used across these papers?"
3. Verify responses include **citations** pointing to source documents

## Step 5: Get Endpoint Information

After testing, note the endpoint details for programmatic access:

1. Click on the agent name to view details
2. Find the **Serving endpoint** name (e.g., `agents_arxiv-papers`)
3. Note the endpoint URL for API calls

## Querying via API

Once you have the endpoint name, you can query programmatically:

```python
from arxiv_demo.query import query_knowledge_assistant

response = query_knowledge_assistant(
    endpoint_name="agents_arxiv-papers",  # Your endpoint name
    question="What are the main themes in these papers?"
)
print(response)
```

Or via curl:

```bash
curl -X POST "https://<workspace>/serving-endpoints/<endpoint>/invocations" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What papers discuss agents?"}]}'
```

## Troubleshooting

### Agent not responding
- Indexing may still be in progress (can take several minutes for many documents)
- Check the agent status in the Agents UI

### No citations in responses
- Ensure documents are properly indexed
- Try more specific questions that reference document content

### Permission errors
- Verify you have access to the UC Volume
- Check that the agent has permissions to read the volume

## Next Steps

- Add more papers to the volume (they'll be indexed automatically)
- Customize the system prompt for better responses
- Integrate with a dashboard (Phase 5)
