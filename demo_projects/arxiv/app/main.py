"""
Arxiv Paper Analysis - Streamlit App

Three-phase workflow:
1. Search - get metadata from arxiv API
2. Review - parse selected papers, review extracted content
3. KA Manager - manage documents in Knowledge Assistant
"""

from datetime import date, timedelta

import streamlit as st

from arxiv_demo.config import DEFAULT_CONFIG
from arxiv_demo.ingestion import ArxivIngestion
from arxiv_demo.kie import KIEClient
from arxiv_demo.parsing import DocumentParser

st.set_page_config(
    page_title="Arxiv Paper Analysis",
    page_icon="📚",
    layout="wide",
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
        # Step 1: Download and upload PDF
        progress.progress(
            (i + 0.25) / total,
            text=f"[{i+1}/{total}] Downloading {paper.arxiv_id}...",
        )

        try:
            ingestion.download_and_upload([paper], delay_seconds=1.0)
        except Exception as e:
            st.error(f"Failed to download {paper.arxiv_id}: {e}")
            st.session_state.parsed_papers[paper.arxiv_id] = {
                "paper": paper,
                "extracted": None,
                "status": "error",
                "error": f"Download failed: {e}",
            }
            continue

        # Step 2: Parse PDF to extract text with ai_parse_document
        progress.progress(
            (i + 0.5) / total,
            text=f"[{i+1}/{total}] Parsing PDF {paper.arxiv_id}... (1-2min)",
        )

        try:
            parsed_doc = parser.parse_document(paper.volume_path, paper.arxiv_id)
        except Exception as e:
            st.error(f"Failed to parse {paper.arxiv_id}: {e}")
            st.session_state.parsed_papers[paper.arxiv_id] = {
                "paper": paper,
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
                "extracted": extracted,
                "status": "complete",
            }
            success_count += 1
        except Exception as e:
            st.error(f"KIE extraction failed for {paper.arxiv_id}: {e}")
            st.session_state.parsed_papers[paper.arxiv_id] = {
                "paper": paper,
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
            # Always use arxiv title for simplicity
            title = paper.title
            
            # Create expander with valid title
            with st.expander(f"{status_icon} **{title}**"):
                # Links row
                col_link1, col_link2 = st.columns([1, 1])
                with col_link1:
                    st.link_button("📄 View PDF", paper.pdf_url)
                with col_link2:
                    clean_id = arxiv_id.replace("v1", "").replace("v2", "").replace("v3", "")
                    st.link_button("🔗 Arxiv Page", f"https://arxiv.org/abs/{clean_id}")

                if status == "error":
                    st.error(f"Error: {data.get('error', 'Unknown error')}")
                    # Still show arxiv metadata
                    st.write("**Abstract (from arxiv):**")
                    st.write(paper.abstract[:500] + "..." if len(paper.abstract) > 500 else paper.abstract)
                elif extracted:
                    # Authors & Affiliation (skip if unknown)
                    authors_str = ", ".join(extracted.authors) if extracted.authors else ", ".join(paper.authors)
                    st.write(f"**Authors:** {authors_str}")
                    if extracted.affiliation and extracted.affiliation not in ("<UNKNOWN>", "Unknown", ""):
                        st.write(f"**Affiliation:** {extracted.affiliation}")

                    # Topics as tags (filter out unknown/generic ones)
                    valid_topics = [t for t in extracted.topics if t and "unknown" not in t.lower()]
                    if valid_topics:
                        st.write("**Topics:**")
                        st.write(" ".join([f"`{t}`" for t in valid_topics]))

                    # Abstract from arxiv
                    with st.container():
                        st.write("**Abstract:**")
                        st.write(paper.abstract[:600] + "..." if len(paper.abstract) > 600 else paper.abstract)

                    # Key contributions
                    if extracted.contributions:
                        st.write("**Key Contributions:**")
                        for contrib in extracted.contributions:
                            st.write(f"- {contrib}")

                    # Methodology
                    if extracted.methodology:
                        st.write("**Methodology:**")
                        st.write(extracted.methodology)

                    # Limitations
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
    """Mark selected papers as in Knowledge Assistant."""
    selected = st.session_state.papers_for_ka

    # The files are already in the volume from the parse step
    # Just need to update state
    st.success(f"Added {len(selected)} papers to Knowledge Assistant!")
    st.info("Papers are already in the UC Volume from the parsing step.")
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
# MAIN
# =============================================================================
def main():
    st.title("📚 Arxiv Paper Analysis")

    tab1, tab2, tab3 = st.tabs(["🔍 Search", "📋 Review", "📁 KA Manager"])

    with tab1:
        search_tab()

    with tab2:
        review_tab()

    with tab3:
        ka_manager_tab()


if __name__ == "__main__":
    main()
