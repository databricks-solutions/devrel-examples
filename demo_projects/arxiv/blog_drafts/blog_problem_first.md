# Building a Knowledge Assistant That Actually Knows Your Research Papers

You're six months into a research project. You've read dozens of papers on LLM agents—ReAct, Reflexion, Voyager, that paper with the interesting ablation study you can't quite remember the name of. You know you saw something about chain-of-thought prompting limitations. Was it in the Reflexion paper? Or was that the one about self-consistency?

You search your downloads folder. Fifty PDFs named "2304.03442.pdf" stare back at you.

This is the reality of staying current in machine learning research. You accumulate papers faster than you can organize them. Paper management tools let you tag and categorize, but they don't understand what's inside. Vector search tools give you keyword matches, but they can't tell you "here's what this paper concluded about model limitations."

What you need is a knowledge assistant that understands the structure and content of research papers—not just a search index, but a system that can extract methodology, limitations, key contributions, and answer questions with citations.

Let's build one.

## The Architecture: Four Phases from Search to Chat

This isn't about dumping random papers into a vector database. The value comes from a curated workflow:

1. **Search and select** papers from Arxiv using filtered queries
2. **Parse and extract** structured information using Databricks AI functions and Agent Bricks
3. **Review and curate** what goes into your knowledge base
4. **Chat** with the assistant using RAG over your curated papers

Each phase addresses a specific part of the research workflow. Here's what makes this approach work:

**Unity Catalog Volumes** provide centralized storage for PDFs. Papers uploaded by one user are available to the entire team, avoiding the "everyone downloads their own copy" problem.

**The `ai_parse_document` SQL function** extracts text from PDFs without managing parsing infrastructure. Pass it a volume path, get back structured text content. This handles the messy reality of PDF formatting—multi-column layouts, figure captions, reference sections.

**Key Information Extraction (KIE) Agent Brick** takes that parsed text and extracts structured fields using a schema you define. Instead of writing custom extraction logic, you configure the agent with a JSON schema describing what you want: title, authors, methodology, limitations, topics.

**Knowledge Assistant (Agent Brick for RAG)** provides cited answers from your curated paper collection. It's RAG with built-in chunking, citation tracking, and evaluation tools.

The result is a system where research papers flow from Arxiv → structured metadata → knowledge base → conversational interface.

## Walking Through the Search and Parse Flow

Start by searching Arxiv with filters that matter for research:

```python
# Build a query that combines keywords with categories and date ranges
query = "large language model agents AND cat:cs.CL AND submittedDate:[20240101 TO *]"
results = ingestion.search_papers(query, max_results=10)
```

The search returns metadata—title, abstract, authors, categories—but not the full paper content. That's by design. You review the metadata first, select papers that look relevant, then process only what you need.

Once you've selected papers, processing happens in three steps:

**Step 1: Download and Upload**
```python
# Download from Arxiv, upload to Unity Catalog Volume
ingestion.download_and_upload(selected_papers)
# Papers now available at: /Volumes/arxiv_demo/main/pdfs/2304.03442.pdf
```

**Step 2: Parse PDF with `ai_parse_document`**
```python
# Extract text content using Databricks SQL function
parsed = parser.parse_document(volume_path, arxiv_id)
# Returns structured text: pages, elements, content
```

Here's what this looks like in the actual SQL execution:

```sql
SELECT ai_parse_document(
  'dbfs:/Volumes/arxiv_demo/main/pdfs/2304.03442.pdf',
  map('format', 'TEXT')
) as parsed_content
```

The function handles complex PDF layouts and returns clean text. No infrastructure to manage, no libraries to version-pin, no "works on my machine" debugging.

**Step 3: Extract Structured Fields with KIE Agent**
```python
# Send parsed text to KIE endpoint
extracted = kie.extract_from_text(parsed.text_content)
# Returns: title, authors, affiliation, contributions, methodology, limitations, topics
```

The KIE agent uses a JSON schema that specifies exactly what you want extracted. Here's a portion of the schema defining methodology extraction:

```json
{
  "methodology": {
    "type": "string",
    "description": "The research methods, experimental designs, techniques, or approaches used to conduct the study. This includes data collection procedures, model architectures, training strategies, evaluation protocols, and any novel technical contributions."
  }
}
```

The schema acts as instruction for the extraction model. Add a field for "datasets used"? Update the schema. Want to track "reproducibility notes"? Add it to the schema. The agent adapts without code changes.

## The Value of Structured Extraction

Why extract structured fields when you could just dump PDFs into a RAG system?

Because structure enables workflows that full-text search can't provide:

**Filter by methodology**: "Show me all papers using reinforcement learning from human feedback"

**Track limitations**: "What papers acknowledge issues with long-context understanding?"

**Find related work**: "Papers in the same topic area as Reflexion but using different evaluation metrics"

Here's what the extracted data looks like for a real paper:

```python
ExtractedPaper(
    title="ReAct: Synergizing Reasoning and Acting in Language Models",
    authors=["Shunyu Yao", "Jeffrey Zhao", "Dian Yu", "Nan Du", ...],
    methodology="Proposes ReAct prompting that interleaves reasoning traces with task-specific actions. Evaluates on question answering (HotpotQA, FEVER) and interactive decision making (ALFWorld, WebShop) benchmarks.",
    limitations=[
        "Requires access to external tools or environments",
        "Performance sensitive to prompt design",
        "May generate incorrect reasoning traces"
    ],
    topics=["reasoning", "agents", "tool use", "question answering"]
)
```

This metadata gets stored in Delta tables alongside the PDFs. Now you can query:

```sql
SELECT title, methodology
FROM arxiv_demo.main.papers
WHERE array_contains(topics, 'reasoning')
  AND methodology LIKE '%reinforcement learning%'
```

Or display it in the UI so reviewers can see contributions and limitations before adding a paper to the knowledge base.

## From Curated Collection to Conversational Interface

After parsing and extraction, you have a review phase. This matters more than you might think.

Not every paper that matches your search query deserves a spot in your knowledge base. Maybe the abstract sounded relevant, but the methodology doesn't fit your use case. Maybe the paper is a survey that summarizes other work you've already read. The review phase lets you inspect extracted fields and make decisions:

- Does the methodology align with what I'm researching?
- Are the limitations deal-breakers for my application?
- Do the contributions add new information to my knowledge base?

Papers in the Unity Catalog Volume are available to the Knowledge Assistant. Once you've curated your collection, deploy a Knowledge Assistant agent pointing to that volume:

```python
# In Databricks UI: Agents → Create Agent → Knowledge Source
# Point to: /Volumes/arxiv_demo/main/pdfs
# Deploy to serving endpoint
```

Now you can chat with your curated research collection. The Knowledge Assistant uses RAG to find relevant chunks and includes citations in responses:

**Query**: "How do ReAct and Reflexion differ in their approach to agent failures?"

**Response**:
"ReAct handles failures through its interleaved reasoning-action traces, where the model generates thoughts before and after each action [1]. When an action fails, the reasoning trace provides context for adjusting the next step.

Reflexion takes a different approach by using episodic memory of past failures to improve performance across task attempts [2]. After completing a task, the model reflects on the trajectory and stores lessons learned for future episodes..."

[1] ReAct: Synergizing Reasoning and Acting in Language Models (2304.03442)
[2] Reflexion: Language Agents with Verbal Reinforcement Learning (2303.11366)

The citations link back to specific papers in your volume. You get answers *and* provenance.

## Putting It Together: The Streamlit Application

The demo implements this workflow in a Streamlit app with four tabs:

**🔍 Search**: Query Arxiv with category filters, date ranges, and keyword search. Select papers to parse.

**📋 Review**: View extracted fields for parsed papers. See methodology, limitations, contributions side-by-side. Select papers to add to Knowledge Assistant.

**📁 KA Manager**: View all papers in your Unity Catalog Volume. Delete papers that are no longer relevant.

**💬 Chat**: Conversational interface to the Knowledge Assistant with streaming responses.

The app demonstrates the full workflow in a single interface. Search, parse, curate, chat—all connected through Unity Catalog and Agent Bricks.

Run it locally during development:
```bash
uv run streamlit run app/main.py
```

Or deploy it as a Databricks App for team access. The same code, the same workflow, available to everyone working on the project.

## Evaluation: Ground Truth for RAG Quality

A knowledge assistant is only useful if it gives accurate answers. The demo includes evaluation infrastructure:

**Create evaluation questions** matched to papers in your collection:
```python
# evaluation_dataset.json contains questions like:
{
  "eval_id": "react_hotpotqa",
  "request": "What benchmark did the ReAct paper use for multi-hop question answering?",
  "expected_retrieved_context": ["ReAct paper"],
  "expected_response": "HotpotQA"
}
```

**Store in Delta table** for the Knowledge Assistant evaluation UI:
```bash
uv run python scripts/create_eval_table.py
# Creates arxiv_demo.main.eval_questions
```

**Run evaluation** in the Databricks Agents UI:
1. Navigate to your Knowledge Assistant agent
2. Evaluation tab → Import from Unity Catalog
3. Select `arxiv_demo.main.eval_questions`
4. Run evaluation and review LLM-as-judge scores

This closes the loop from ingestion to evaluation. You know whether your knowledge assistant is retrieving the right papers and generating accurate responses.

## Next Steps: Extending the Workflow

This demo establishes the core pattern: search → parse → extract → curate → chat. Here's how you might extend it:

**Add more extraction fields**: Update the KIE schema to capture datasets used, evaluation metrics, or model sizes.

**Implement semantic filtering**: Use embeddings to find papers similar to a reference paper, even if they don't share keywords.

**Connect to your research**: Replace Arxiv search with imports from Zotero, Mendeley, or internal research databases.

**Automate curation**: Add a review agent that scores papers based on relevance to your research area, flagging high-priority papers for human review.

**Multi-agent workflows**: Combine the KIE agent with other Agent Bricks—summarization for abstracts, comparison agents for methodology differences.

The tools are composable. Unity Catalog provides shared storage. Agent Bricks handle specialized tasks. Delta tables track metadata. The Knowledge Assistant provides RAG with citations.

You're not building a PDF search index. You're building a research assistant that understands your domain.

---

**Ready to try it?** The full code is available at [repository link]. Clone the repo, follow the setup in `README.md`, and run the Streamlit app. Deploy your own Knowledge Assistant in under an hour.

The papers you need to find won't be buried in your downloads folder anymore.
