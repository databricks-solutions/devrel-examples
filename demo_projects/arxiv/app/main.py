"""
Arxiv Paper Analysis - Streamlit App

Four-phase workflow:
1. Search - get metadata from arxiv API
2. Review - parse selected papers, review extracted content
3. KA Manager - manage documents in Knowledge Assistant
4. Chat - query the Knowledge Assistant
"""

from datetime import date, timedelta

import streamlit as st
from openai import OpenAI
from databricks.sdk import WorkspaceClient

from src.config import DEFAULT_CONFIG
from src.ingestion import ArxivIngestion, DocumentParser, KIEClient

# Get KA endpoint from config
KA_ENDPOINT = DEFAULT_CONFIG.ka_endpoint

st.set_page_config(
    page_title="Arxiv Paper Analysis",
    page_icon="📚",
    layout="centered",
)

# Initialize session state
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "papers_to_parse" not in st.session_state:
    st.session_state.papers_to_parse = set()
if "parsed_papers" not in st.session_state:
    st.session_state.parsed_papers = {}  # arxiv_id -> parsed content
if "papers_for_ka" not in st.session_state:
    st.session_state.papers_for_ka = set()
if "messages" not in st.session_state:
    st.session_state.messages = []


@st.cache_resource
def get_ingestion():
    """Get cached ingestion client."""
    return ArxivIngestion()


@st.cache_resource
def get_kie_client():
    """Get cached KIE client."""
    return KIEClient()


@st.cache_resource
def get_parser():
    """Get cached document parser."""
    return DocumentParser()


# =============================================================================
# PHASE 1: SEARCH
# =============================================================================

# Common arxiv categories for AI/ML/NLP papers
ARXIV_CATEGORIES = {
    "cs.CL": "Computation & Language (NLP, LLMs)",
    "cs.AI": "Artificial Intelligence",
    "cs.LG": "Machine Learning",
    "cs.CV": "Computer Vision",
    "cs.NE": "Neural & Evolutionary Computing",
    "stat.ML": "Statistics - Machine Learning",
}


def build_query(
    keywords: str,
    categories: list[str],
    title_only: bool,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Build arxiv query string from components."""
    parts = []

    # Add keyword search
    if keywords.strip():
        if title_only:
            # Search in title only for more precision
            parts.append(f"ti:{keywords}")
        else:
            parts.append(keywords)

    # Add category filter
    if categories:
        cat_query = " OR ".join(f"cat:{cat}" for cat in categories)
        if len(categories) > 1:
            cat_query = f"({cat_query})"
        parts.append(cat_query)

    # Add date range filter
    if date_from or date_to:
        start = date_from.replace("-", "") + "0000" if date_from else "*"
        end = date_to.replace("-", "") + "2359" if date_to else "*"
        parts.append(f"submittedDate:[{start} TO {end}]")

    return " AND ".join(parts) if parts else "machine learning"


def search_tab():
    """Search arxiv and select papers to parse."""
    st.header("Phase 1: Search Arxiv")
    st.caption("Search for papers, then select which ones to parse with ai_parse_document")

    # Search controls - Keywords
    col1, col2 = st.columns([3, 1])
    with col1:
        keywords = st.text_input(
            "Keywords",
            value="large language model agents",
            help="Search terms (e.g., 'transformer', 'RAG retrieval')",
        )
    with col2:
        max_results = st.number_input("Max results", min_value=1, max_value=50, value=10)

    # Category filters
    st.write("**Categories** (select for more relevant results)")
    selected_cats = []
    cols = st.columns(3)
    for i, (cat_id, cat_name) in enumerate(ARXIV_CATEGORIES.items()):
        with cols[i % 3]:
            # Default select cs.CL for LLM relevance
            default = cat_id in ["cs.CL", "cs.AI"]
            if st.checkbox(f"{cat_id}", value=default, help=cat_name):
                selected_cats.append(cat_id)

    # Date range filter
    st.write("**Date range** (submission date)")
    date_col1, date_col2 = st.columns(2)
    with date_col1:
        # Default to 6 months ago
        default_from = date.today() - timedelta(days=180)
        date_from = st.date_input("From", value=default_from)
    with date_col2:
        date_to = st.date_input("To", value=date.today())

    # Advanced options
    title_only = st.checkbox(
        "Title search only",
        value=False,
        help="More precise: search only in paper titles",
    )

    # Build query from all components
    query = build_query(
        keywords,
        selected_cats,
        title_only,
        date_from=str(date_from) if date_from else None,
        date_to=str(date_to) if date_to else None,
    )

    # Show the query being used
    st.caption(f"Query: `{query}`")

    if st.button("🔍 Search", type="primary"):
        with st.spinner("Searching arxiv..."):
            ingestion = get_ingestion()
            results = ingestion.search_papers(query, max_results=max_results)
            st.session_state.search_results = results
            st.session_state.papers_to_parse = set()

    # Display results
    if st.session_state.search_results:
        st.subheader(f"Results ({len(st.session_state.search_results)} papers)")

        # Selection controls
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        with col1:
            if st.button("Select All"):
                st.session_state.papers_to_parse = {
                    p.arxiv_id for p in st.session_state.search_results
                }
                st.rerun()
        with col2:
            if st.button("Clear Selection"):
                st.session_state.papers_to_parse = set()
                st.rerun()

        # Paper list
        for paper in st.session_state.search_results:
            col1, col2 = st.columns([0.05, 0.95])
            with col1:
                selected = st.checkbox(
                    "sel",
                    value=paper.arxiv_id in st.session_state.papers_to_parse,
                    key=f"parse_{paper.arxiv_id}",
                    label_visibility="collapsed",
                )
                if selected:
                    st.session_state.papers_to_parse.add(paper.arxiv_id)
                else:
                    st.session_state.papers_to_parse.discard(paper.arxiv_id)

            with col2:
                # Check if already parsed
                already_parsed = paper.arxiv_id in st.session_state.parsed_papers
                status = "✅ Parsed" if already_parsed else ""

                with st.expander(f"**{paper.title[:80]}{'...' if len(paper.title) > 80 else ''}** {status}"):
                    st.caption(f"arxiv:{paper.arxiv_id} | {paper.published[:10]} | {', '.join(paper.categories[:3])}")
                    authors_str = ", ".join(paper.authors[:3])
                    if len(paper.authors) > 3:
                        authors_str += f" +{len(paper.authors) - 3} more"
                    st.write(f"**Authors:** {authors_str}")
                    st.write("**Abstract:**")
                    abstract = paper.abstract[:400] + "..." if len(paper.abstract) > 400 else paper.abstract
                    st.write(abstract)

        # Parse button
        selected_count = len(st.session_state.papers_to_parse)
        if selected_count > 0:
            st.divider()
            st.success(f"{selected_count} paper(s) selected for parsing")
            if st.button(f"📄 Parse {selected_count} Paper(s)", type="primary"):
                parse_selected_papers()


def parse_selected_papers():
    """Download papers, parse with ai_parse_document, and extract fields using KIE agent."""
    selected_ids = st.session_state.papers_to_parse
    papers_to_process = [
        p for p in st.session_state.search_results if p.arxiv_id in selected_ids
    ]

    if not papers_to_process:
        st.warning("No papers selected")
        return

    ingestion = get_ingestion()
    parser = get_parser()
    kie = get_kie_client()
    progress = st.progress(0, text="Starting...")

    success_count = 0
    total = len(papers_to_process)

    for i, paper in enumerate(papers_to_process):
        # Step 1: Download PDF and upload to STAGING volume (not KA volume)
        progress.progress(
            (i + 0.25) / total,
            text=f"[{i+1}/{total}] Downloading {paper.arxiv_id}...",
        )

        try:
            staging_path = ingestion.download_to_staging(paper)
        except Exception as e:
            st.error(f"Failed to download {paper.arxiv_id}: {e}")
            st.session_state.parsed_papers[paper.arxiv_id] = {
                "paper": paper,
                "staging_path": None,
                "extracted": None,
                "status": "error",
                "error": f"Download failed: {e}",
            }
            continue

        # Step 2: Parse PDF from staging volume with ai_parse_document
        progress.progress(
            (i + 0.5) / total,
            text=f"[{i+1}/{total}] Parsing PDF {paper.arxiv_id}... (1-2min)",
        )

        try:
            parsed_doc = parser.parse_document(staging_path, paper.arxiv_id)
        except Exception as e:
            st.error(f"Failed to parse {paper.arxiv_id}: {e}")
            st.session_state.parsed_papers[paper.arxiv_id] = {
                "paper": paper,
                "staging_path": staging_path,
                "extracted": None,
                "status": "error",
                "error": f"Parse failed: {e}",
            }
            continue

        # Step 3: Extract structured fields with KIE agent
        progress.progress(
            (i + 0.8) / total,
            text=f"[{i+1}/{total}] Extracting fields from {paper.arxiv_id}... (30-60s)",
        )

        try:
            extracted = kie.extract_from_text(parsed_doc.text_content, paper.arxiv_id)
            st.session_state.parsed_papers[paper.arxiv_id] = {
                "paper": paper,
                "staging_path": staging_path,
                "extracted": extracted,
                "status": "complete",
            }
            success_count += 1
        except Exception as e:
            st.error(f"KIE extraction failed for {paper.arxiv_id}: {e}")
            st.session_state.parsed_papers[paper.arxiv_id] = {
                "paper": paper,
                "staging_path": staging_path,
                "extracted": None,
                "status": "error",
                "error": f"KIE failed: {e}",
            }

        progress.progress((i + 1) / total, text=f"Completed {i + 1}/{total}")

    progress.empty()
    st.success(f"Processed {success_count}/{total} papers. Go to Review tab to review.")
    st.session_state.papers_to_parse = set()


# =============================================================================
# PHASE 2: REVIEW
# =============================================================================
def review_tab():
    """Review extracted paper information and select for Knowledge Assistant."""
    st.header("Phase 2: Review Extracted Papers")
    st.caption("Review KIE-extracted fields and select papers to add to Knowledge Assistant")

    if not st.session_state.parsed_papers:
        st.info("No papers to review yet. Use the Search tab to find and process papers.")
        return

    # Selection controls
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Select All for KA"):
            st.session_state.papers_for_ka = set(st.session_state.parsed_papers.keys())
            st.rerun()
    with col2:
        if st.button("Clear KA Selection"):
            st.session_state.papers_for_ka = set()
            st.rerun()

    # Display papers with extracted info
    for arxiv_id, data in st.session_state.parsed_papers.items():
        paper = data["paper"]
        extracted = data.get("extracted")
        status = data.get("status", "unknown")

        col1, col2 = st.columns([0.05, 0.95])
        with col1:
            selected = st.checkbox(
                "ka",
                value=arxiv_id in st.session_state.papers_for_ka,
                key=f"ka_{arxiv_id}",
                label_visibility="collapsed",
            )
            if selected:
                st.session_state.papers_for_ka.add(arxiv_id)
            else:
                st.session_state.papers_for_ka.discard(arxiv_id)

        with col2:
            status_icon = "✅" if status == "complete" else "❌"
            title = paper.title[:70] + "..." if len(paper.title) > 70 else paper.title

            # Show topics as inline tags if available
            topics_str = ""
            if extracted and extracted.topics:
                valid_topics = [t for t in extracted.topics[:3] if t and "unknown" not in t.lower()]
                if valid_topics:
                    topics_str = " · " + " ".join([f"`{t}`" for t in valid_topics])

            with st.expander(f"{status_icon} **{title}**{topics_str}"):
                if status == "error":
                    st.error(f"Error: {data.get('error', 'Unknown error')}")
                    st.write(paper.abstract[:500] + "..." if len(paper.abstract) > 500 else paper.abstract)
                elif extracted:
                    # Abstract first - most interesting
                    st.write(paper.abstract)

                    st.divider()

                    # Compact metadata row
                    authors_short = ", ".join(paper.authors[:3])
                    if len(paper.authors) > 3:
                        authors_short += f" +{len(paper.authors) - 3} more"
                    st.caption(f"**Authors:** {authors_short}")

                    # Links
                    col_link1, col_link2 = st.columns([1, 1])
                    with col_link1:
                        st.link_button("📄 PDF", paper.pdf_url)
                    with col_link2:
                        clean_id = arxiv_id.replace("v1", "").replace("v2", "").replace("v3", "")
                        st.link_button("🔗 Arxiv", f"https://arxiv.org/abs/{clean_id}")

                    # KIE-extracted insights (collapsible)
                    if extracted.contributions or extracted.methodology or extracted.limitations:
                        with st.expander("📊 KIE-Extracted Insights"):
                            if extracted.contributions:
                                st.write("**Key Contributions:**")
                                for contrib in extracted.contributions:
                                    st.write(f"- {contrib}")
                            if extracted.methodology:
                                st.write("**Methodology:**")
                                st.write(extracted.methodology)
                            if extracted.limitations:
                                st.write("**Limitations:**")
                                for lim in extracted.limitations:
                                    st.write(f"- {lim}")
                else:
                    st.info("Extraction pending")

    # Add to KA button
    ka_count = len(st.session_state.papers_for_ka)
    if ka_count > 0:
        st.divider()
        st.success(f"{ka_count} paper(s) selected for Knowledge Assistant")
        if st.button(f"📚 Add {ka_count} Paper(s) to Knowledge Assistant", type="primary"):
            add_to_knowledge_assistant()


def add_to_knowledge_assistant():
    """Copy selected papers from staging to KA volume."""
    selected = st.session_state.papers_for_ka
    if not selected:
        st.warning("No papers selected")
        return

    ingestion = get_ingestion()
    progress = st.progress(0, text="Adding papers to Knowledge Assistant...")

    success_count = 0
    total = len(selected)

    for i, arxiv_id in enumerate(selected):
        data = st.session_state.parsed_papers.get(arxiv_id)
        if not data:
            st.error(f"No data found for {arxiv_id}")
            continue

        paper = data["paper"]
        staging_path = data.get("staging_path")
        if not staging_path:
            st.error(f"No staging path for {arxiv_id}")
            continue

        progress.progress(
            (i + 0.5) / total,
            text=f"[{i+1}/{total}] Adding {arxiv_id} to Knowledge Assistant...",
        )

        try:
            ingestion.promote_to_ka(paper, staging_path)
            success_count += 1
        except Exception as e:
            st.error(f"Failed to add {arxiv_id}: {e}")

        progress.progress((i + 1) / total, text=f"Completed {i + 1}/{total}")

    progress.empty()
    st.success(f"Added {success_count}/{total} papers to Knowledge Assistant!")
    st.info("Sync your Knowledge Assistant to pick up the new documents.")

    # Clear selection
    st.session_state.papers_for_ka = set()


# =============================================================================
# PHASE 3: KA MANAGER
# =============================================================================

# Session state for selected papers to delete
if "papers_to_delete" not in st.session_state:
    st.session_state.papers_to_delete = set()


def ka_manager_tab():
    """Manage Knowledge Assistant documents."""
    st.header("Phase 3: Knowledge Assistant Manager")
    st.caption("View and manage documents in your Knowledge Assistant")

    ingestion = get_ingestion()

    # Get papers from Delta table (persistent storage)
    papers_from_db = ingestion.get_all_papers()
    papers_lookup = {p["arxiv_id"]: p for p in papers_from_db}

    # Get file list
    files = ingestion.list_uploaded_files()

    if not files and not papers_from_db:
        st.info("No documents in Knowledge Assistant yet.")
        st.write("Use the Search → Review workflow to add papers.")
        return

    # Control buttons row
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    with col1:
        if st.button("🔄 Refresh", key="ka_refresh"):
            st.rerun()
    with col2:
        if st.button("Select All", key="ka_select_all"):
            st.session_state.papers_to_delete = {f.split("/")[-1].replace(".pdf", "") for f in files}
            st.rerun()
    with col3:
        if st.button("Clear Selection", key="ka_clear_sel"):
            st.session_state.papers_to_delete = set()
            st.rerun()

    st.caption(f"Volume: `{ingestion.config.volume_path}` | {len(files)} documents")

    # Paper list
    for file_path in files:
        filename = file_path.split("/")[-1]
        arxiv_id = filename.replace(".pdf", "")
        clean_id = arxiv_id.replace("v1", "").replace("v2", "").replace("v3", "")

        # Get metadata from Delta table
        paper_data = papers_lookup.get(arxiv_id, {})
        title = paper_data.get("title")
        authors = paper_data.get("authors")

        col_check, col_info, col_link = st.columns([0.5, 8, 1])

        with col_check:
            selected = st.checkbox(
                "sel",
                value=arxiv_id in st.session_state.papers_to_delete,
                key=f"del_{arxiv_id}",
                label_visibility="collapsed",
            )
            if selected:
                st.session_state.papers_to_delete.add(arxiv_id)
            else:
                st.session_state.papers_to_delete.discard(arxiv_id)

        with col_info:
            if title:
                # Compact display: title with authors on same line
                authors_str = ""
                if authors:
                    if isinstance(authors, str):
                        authors_str = authors
                    else:
                        authors_str = ", ".join(authors[:2])
                        if len(authors) > 2:
                            authors_str += f" +{len(authors) - 2}"
                st.markdown(f"**{title[:55]}{'...' if len(title) > 55 else ''}** · {authors_str} · `{arxiv_id}`")
            else:
                st.markdown(f"**{arxiv_id}**")

        with col_link:
            st.link_button("arxiv", f"https://arxiv.org/abs/{clean_id}")

    # Delete selected button
    selected_count = len(st.session_state.papers_to_delete)
    if selected_count > 0:
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            st.warning(f"{selected_count} paper(s) selected for deletion")
        with col2:
            if st.button(f"🗑️ Delete {selected_count} Paper(s)", type="primary"):
                for arxiv_id in list(st.session_state.papers_to_delete):
                    ingestion.delete_paper(arxiv_id)
                st.session_state.papers_to_delete = set()
                st.success(f"Deleted {selected_count} papers")
                st.rerun()


# =============================================================================
# PHASE 4: CHAT
# =============================================================================

def get_openai_client():
    """Get OpenAI client configured for Databricks.

    Uses the SDK's built-in method which handles both:
    - Databricks Apps: OAuth credentials (DATABRICKS_CLIENT_ID/SECRET)
    - Local dev: CLI profile or PAT token
    """
    ws_client = WorkspaceClient(profile=DEFAULT_CONFIG.profile)
    return ws_client.serving_endpoints.get_open_ai_client()


def chat_with_ka(messages: list[dict]) -> str:
    """Chat with Knowledge Assistant agent using OpenAI responses API."""
    if not KA_ENDPOINT:
        raise ValueError("Knowledge Assistant endpoint not configured. Set KA_ENDPOINT env var.")

    try:
        client = get_openai_client()
    except ValueError as e:
        raise ValueError(f"Authentication error: {e}")

    # Use the responses API for Knowledge Assistant
    try:
        response = client.responses.create(
            model=KA_ENDPOINT,
            input=[{"role": msg["role"], "content": msg["content"]} for msg in messages],
        )
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ValueError(f"Permission error: {e}")
        raise

    # Extract text from response
    texts = []
    for output in response.output:
        if hasattr(output, "content"):
            for content in output.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
    return " ".join(texts) if texts else str(response)


def chat_tab():
    """Chat with the Knowledge Assistant."""
    st.header("Phase 4: Chat with Assistant")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption("Ask questions to your Knowledge Assistant (RAG)")
    with col2:
        if st.button("🔄 New Chat", key="new_chat"):
            st.session_state.messages = []
            st.rerun()

    if not KA_ENDPOINT:
        st.warning("Knowledge Assistant endpoint not configured. Set KA_ENDPOINT in .env or config.")
        return

    # Create a container for messages - height provides scrollable area
    chat_container = st.container(height=400)

    # Display chat messages in the container
    with chat_container:
        if not st.session_state.messages:
            st.caption("Ask questions about papers in your Knowledge Assistant.")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Chat input below the container
    if prompt := st.chat_input("Ask a question about the papers..."):
        # Add user message to history and display it
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

            # Get and display assistant response
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    try:
                        response = chat_with_ka(st.session_state.messages)
                    except Exception as e:
                        response = f"Error: {e}"
                st.markdown(response)

        # Add assistant response to history
        st.session_state.messages.append({"role": "assistant", "content": response})


# =============================================================================
# MAIN
# =============================================================================
def main():
    st.title("📚 Arxiv Paper Analysis")

    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search", "📋 Review", "📁 KA Manager", "💬 Chat"])

    with tab1:
        search_tab()

    with tab2:
        review_tab()

    with tab3:
        ka_manager_tab()

    with tab4:
        chat_tab()


if __name__ == "__main__":
    main()
