-- Create tables for arxiv demo
-- Note: DEFAULT values removed for compatibility

-- Papers metadata table
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.papers (
    arxiv_id STRING NOT NULL,
    title STRING,
    authors ARRAY<STRING>,
    abstract STRING,
    published_date TIMESTAMP,
    updated_date TIMESTAMP,
    categories ARRAY<STRING>,
    pdf_url STRING,
    volume_path STRING,
    in_knowledge_assistant BOOLEAN,
    ingested_at TIMESTAMP
);

-- Parsed documents table (ai_parse_document output)
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.parsed_documents (
    arxiv_id STRING NOT NULL,
    parsed_content STRING,
    page_count INT,
    element_count INT,
    has_tables BOOLEAN,
    has_figures BOOLEAN,
    parsed_at TIMESTAMP
)
