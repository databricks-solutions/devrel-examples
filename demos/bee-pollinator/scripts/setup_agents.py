"""
Bee Pollinator Demo - Agent Setup Script

Creates a Genie Space and Knowledge Assistant using the Databricks SDK.
The Supervisor Agent must still be created manually via the UI.

Prerequisites:
- Databricks workspace with Unity Catalog enabled
- Delta tables created (run setup_data.py first)
- PDFs uploaded to UC Volume
- Python packages: databricks-sdk

Usage:
    python setup_agents.py --catalog your_catalog --schema bee_health --warehouse-id your_warehouse_id

    # With specific profile
    python setup_agents.py --catalog your_catalog --schema bee_health --warehouse-id your_warehouse_id --profile your_profile
"""

import argparse
import json
import sys
import uuid

try:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.knowledgeassistants import (
        FilesSpec,
        KnowledgeAssistant,
        KnowledgeSource,
    )
except ImportError as _import_err:
    # When run as CLI, exit immediately. When imported as a module (e.g. from
    # a Databricks notebook), raise so the caller sees a clear error.
    if __name__ == "__main__":
        print(
            "Error: databricks-sdk not installed or too old. "
            "Run: pip install --upgrade databricks-sdk"
        )
        sys.exit(1)
    raise ImportError(
        "databricks-sdk is missing or too old — "
        "run: pip install --upgrade databricks-sdk"
    ) from _import_err


# Agent instructions templates
GENIE_INSTRUCTIONS = """You are a USDA bee colony health data analyst. You have access to three tables:

1. **honey_production** — State-level honey production data (2015-2025)
   - Columns: state, year, production, yield_per_colony, colonies, price_per_lb
   - Use for: production trends, yield analysis, colony counts, pricing

2. **colony_loss** — Colony deadout loss data (2015-2025)
   - Columns: state, year, quarter, loss_pct, loss_colonies
   - Use for: loss trends by state and quarter, identifying high-loss regions

3. **colony_stressors** — Colony stressor data (2015-2025)
   - Columns: state, year, quarter, stressor, pct_affected
   - Stressors: Varroa Mites, Pesticides, Disease, Pests (Excl Varroa Mites), Other Causes, Unknown Causes
   - Use for: identifying which stressors drive colony loss, seasonal stressor patterns

**Query Guidelines:**
- Join tables on `state` and `year` (and `quarter` for loss + stressors) when combining data
- Use aggregations (SUM, AVG, MAX) for trend analysis
- Filter by state or year range as needed
- When asked about "top N" states, use ORDER BY and LIMIT
- For colony health questions, combine colony_loss and colony_stressors
- For economic questions, use honey_production (price data)
- For stressor analysis, correlate colony_stressors with colony_loss

**Example Queries:**
- "Top 5 states by honey production in 2024" → SELECT state, production FROM honey_production WHERE year = 2024 ORDER BY production DESC LIMIT 5
- "States with highest loss rates" → SELECT state, AVG(loss_pct) as avg_loss FROM colony_loss GROUP BY state ORDER BY avg_loss DESC
- "Which stressors affect the most colonies?" → SELECT stressor, AVG(pct_affected) as avg_pct FROM colony_stressors GROUP BY stressor ORDER BY avg_pct DESC
"""

KA_INSTRUCTIONS = """You are a bee colony health and pollinator conservation expert. You have access to four key documents:

1. **Tools for Varroa Management (8th Edition)** — Varroa mite sampling methods, treatment options, IPM protocols, treatment thresholds (3% spring, 2% fall)

2. **USDA Annual Strategic Pollinator Priorities Report (2022)** — Federal pollinator research coordination, conservation programs (EQIP, CRP), policy initiatives

3. **Supporting Pollinators in Agricultural Landscapes** — Farm management practices for specialty crops, habitat corridors, pesticide risk reduction, IPM strategies

4. **Pollinator-Friendly Plants for the Northeast United States** — Native plant species lists, bloom times, establishment guidelines, habitat creation

**Response Guidelines:**
- Cite specific sections and page numbers when available
- Provide actionable recommendations based on the documents
- Connect policy guidance to practical implementation
- For varroa questions, reference treatment thresholds and monitoring methods
- For habitat questions, recommend native plant species with bloom times
- For farm management, emphasize IPM and pesticide-free buffer zones

**Example Responses:**
- Varroa monitoring → Cite alcohol wash or sugar roll methods, treatment thresholds (3% spring, 2% fall)
- Habitat creation → Reference native plant lists, seasonal bloom coverage, establishment tips
- Federal programs → Detail EQIP funding, CRP eligibility, application process
"""

SUPERVISOR_INSTRUCTIONS = """You are a bee colony health and pollinator conservation advisor. You help beekeepers, farmers, and agricultural extension agents by combining USDA data analysis with expert guidance from beekeeping and conservation documents.

**Route questions as follows:**

1. **Data/Statistics Questions → Genie Space (USDA Bee Health Data)**
   - Questions about honey production, colony counts, trends over time
   - Questions about colony loss rates, stressors by state/year
   - Examples:
     • "Which states had highest colony loss in 2023?"
     • "Show honey production trends in California over last 5 years"
     • "What is the average price per lb of honey in 2024?"

2. **Guidance/Best Practices Questions → Knowledge Assistant (Beekeeping Docs)**
   - Questions about varroa mite management, treatment protocols
   - Questions about USDA programs, conservation funding
   - Questions about habitat creation, native plants
   - Questions about farm management, IPM strategies
   - Examples:
     • "What are recommended varroa treatment methods?"
     • "Which native plants support pollinators in spring?"
     • "What USDA programs fund pollinator habitat?"

3. **Combined Questions → Both Agents**
   - Questions that need BOTH data insight AND expert guidance
   - Data establishes context, documents provide actionable recommendations
   - Examples:
     • "California lost 35% of colonies. What varroa management should they prioritize?"
       → Genie: confirm CA loss rate, identify varroa as top stressor
       → KA: retrieve varroa treatment protocols for CA climate
     • "North Dakota produces the most honey but has high colony loss. What management practices should they adopt?"
       → Genie: show ND production and loss data
       → KA: recommend varroa management and habitat practices

**Synthesis Guidelines:**
- When using both agents, clearly connect the data insight to the document guidance
- Provide specific, actionable recommendations
- Cite data sources (USDA tables) and document sections
- Focus on practical next steps for the user

**Tone:** Professional, helpful, evidence-based. You're advising agricultural professionals.
"""


GENIE_DESCRIPTION = (
    "USDA bee colony health data analyst with access to honey production, "
    "colony loss, and colony stressor tables."
)

KA_DESCRIPTION = (
    "Bee colony health and pollinator conservation expert with access to "
    "varroa management guides, USDA conservation programs, farm IPM "
    "practices, and native plant recommendations."
)

KA_SOURCE_NAME = "Bee Health Guidance PDFs"


def _genie_id() -> str:
    """Generate a stable-shaped identifier for serialized Genie payload items."""
    return uuid.uuid4().hex


def _require_sdk_capability(obj, capability: str, upgrade_hint: str):
    """Fail fast with a clear upgrade message when newer SDK APIs are missing."""
    if not hasattr(obj, capability):
        raise RuntimeError(upgrade_hint)


def _build_genie_serialized_space(catalog: str, schema: str) -> str:
    """Build the serialized Genie Space payload for the bee health demo."""
    honey_table = f"{catalog}.{schema}.honey_production"
    loss_table = f"{catalog}.{schema}.colony_loss"
    stressor_table = f"{catalog}.{schema}.colony_stressors"

    serialized_space = {
        "version": 2,
        "config": {
            "sample_questions": sorted(
                [
                    {
                        "id": _genie_id(),
                        "question": ["What are the top 5 states by honey production in 2024?"],
                    },
                    {
                        "id": _genie_id(),
                        "question": ["Which states have the highest average colony loss rates?"],
                    },
                    {
                        "id": _genie_id(),
                        "question": ["Which stressors affect the most colonies?"],
                    },
                ],
                key=lambda x: x["id"],
            )
        },
        "data_sources": {
            "tables": sorted(
                [
                    {
                        "identifier": honey_table,
                        "description": [
                            "State-level honey production data from 2015-2025, including "
                            "production, yield_per_colony, colonies, and price_per_lb."
                        ],
                    },
                    {
                        "identifier": loss_table,
                        "description": [
                            "Quarterly colony deadout loss data from 2015-2025, including "
                            "loss_pct and loss_colonies by state, year, and quarter."
                        ],
                    },
                    {
                        "identifier": stressor_table,
                        "description": [
                            "Quarterly colony stressor data from 2015-2025, including "
                            "Varroa Mites, Pesticides, Disease, and other causes by "
                            "state, year, and quarter."
                        ],
                    },
                ],
                key=lambda t: t["identifier"],
            )
        },
        "instructions": {
            "text_instructions": [
                {
                    "id": _genie_id(),
                    "content": [GENIE_INSTRUCTIONS],
                }
            ],
            "example_question_sqls": sorted(
                [
                    {
                        "id": _genie_id(),
                        "question": ["Top 5 states by honey production in 2024"],
                        "sql": [
                            f"SELECT state, production FROM {honey_table} "
                            "WHERE year = 2024 ORDER BY production DESC LIMIT 5"
                        ],
                    },
                    {
                        "id": _genie_id(),
                        "question": ["States with highest loss rates"],
                        "sql": [
                            f"SELECT state, AVG(loss_pct) AS avg_loss FROM {loss_table} "
                            "GROUP BY state ORDER BY avg_loss DESC"
                        ],
                    },
                    {
                        "id": _genie_id(),
                        "question": ["Which stressors affect the most colonies?"],
                        "sql": [
                            f"SELECT stressor, AVG(pct_affected) AS avg_pct "
                            f"FROM {stressor_table} GROUP BY stressor ORDER BY avg_pct DESC"
                        ],
                    },
                ],
                key=lambda x: x["id"],
            ),
        },
    }

    return json.dumps(serialized_space)


def create_genie_space(
    w: WorkspaceClient,
    catalog: str,
    schema: str,
    warehouse_id: str,
    space_name: str,
) -> str:
    """Create a Genie Space with the bee health demo tables and instructions."""
    print(f"\nCreating Genie Space: {space_name}")
    _require_sdk_capability(
        w,
        "genie",
        "This databricks-sdk version does not expose Genie APIs. "
        "Run: pip install --upgrade databricks-sdk",
    )
    _require_sdk_capability(
        w.genie,
        "create_space",
        "This databricks-sdk version does not expose w.genie.create_space. "
        "Run: pip install --upgrade databricks-sdk",
    )

    space = w.genie.create_space(
        warehouse_id=warehouse_id,
        title=space_name,
        description=GENIE_DESCRIPTION,
        serialized_space=_build_genie_serialized_space(catalog, schema),
    )

    print(f"  ✓ Genie Space created: {space.space_id}")
    return space.space_id


def _get_existing_knowledge_assistant(
    w: WorkspaceClient, display_name: str
) -> KnowledgeAssistant | None:
    """Look up an existing Knowledge Assistant by display name."""
    for assistant in w.knowledge_assistants.list_knowledge_assistants():
        if assistant.display_name == display_name:
            return assistant
    return None


def _get_existing_knowledge_source(
    w: WorkspaceClient, parent: str, volume_path: str
) -> KnowledgeSource | None:
    """Look up an existing volume-backed knowledge source for an assistant."""
    for source in w.knowledge_assistants.list_knowledge_sources(parent=parent):
        if source.files and source.files.path == volume_path:
            return source
    return None


def _knowledge_assistant_name(assistant: KnowledgeAssistant) -> str:
    """Return the resource name for a Knowledge Assistant."""
    if assistant.name:
        return assistant.name
    if assistant.id:
        return f"knowledge-assistants/{assistant.id}"
    raise RuntimeError("Knowledge Assistant response did not include a resource name.")


def create_knowledge_assistant(
    w: WorkspaceClient, catalog: str, schema: str, volume: str, ka_name: str
) -> str:
    """Create or reuse a Knowledge Assistant and attach the bee health volume."""
    print(f"\nCreating Knowledge Assistant: {ka_name}")
    _require_sdk_capability(
        w,
        "knowledge_assistants",
        "This databricks-sdk version does not expose Knowledge Assistant APIs. "
        "Run: pip install --upgrade databricks-sdk",
    )

    volume_path = f"/Volumes/{catalog}/{schema}/{volume}"
    assistant = _get_existing_knowledge_assistant(w, ka_name)

    if assistant is None:
        assistant = w.knowledge_assistants.create_knowledge_assistant(
            knowledge_assistant=KnowledgeAssistant(
                display_name=ka_name,
                description=KA_DESCRIPTION,
                instructions=KA_INSTRUCTIONS,
            )
        )
        print(f"  ✓ Knowledge Assistant created: {assistant.id}")
    else:
        print(f"  ✓ Knowledge Assistant already exists: {assistant.id}")

    assistant_name = _knowledge_assistant_name(assistant)
    existing_source = _get_existing_knowledge_source(w, assistant_name, volume_path)

    if existing_source is None:
        source = w.knowledge_assistants.create_knowledge_source(
            parent=assistant_name,
            knowledge_source=KnowledgeSource(
                display_name=KA_SOURCE_NAME,
                description="Bee pollinator guidance PDFs stored in a Unity Catalog Volume.",
                source_type="files",
                files=FilesSpec(path=volume_path),
            ),
        )
        print(f"  ✓ Knowledge source added: {source.name}")
    else:
        print(f"  ✓ Knowledge source already exists: {existing_source.name}")

    print(f"  ↻ Syncing knowledge sources from: {volume_path}")
    w.knowledge_assistants.sync_knowledge_sources(name=assistant_name)
    print("  ✓ Knowledge Assistant sync triggered")

    return assistant_name


def print_supervisor_instructions(genie_name: str, ka_name: str):
    """Print Supervisor Agent creation instructions."""
    print("\n" + "="*60)
    print("SUPERVISOR AGENT CREATION (Manual - No API Available)")
    print("="*60)

    print("\n📋 Manual Supervisor Agent Creation Steps:")
    print("  1. Navigate to 'AI Playground' → 'Agents' in your workspace")
    print("  2. Create new 'Supervisor Agent'")
    print("  3. Name: Bee Colony Health Advisor")
    print("  4. Add tools/agents:")
    print(f"     - Add the Genie Space you created ({genie_name})")
    print(f"     - Add the Knowledge Assistant you created ({ka_name})")
    print("  5. Supervisor Instructions: Copy from SUPERVISOR_INSTRUCTIONS below")
    print("\n" + "="*60)
    print("SUPERVISOR INSTRUCTIONS:")
    print("="*60)
    print(SUPERVISOR_INSTRUCTIONS)
    print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Setup bee pollinator demo agents")
    parser.add_argument("--catalog", required=True, help="Unity Catalog name")
    parser.add_argument("--schema", required=True, help="Schema name (e.g., bee_health)")
    parser.add_argument("--warehouse-id", required=True, help="SQL Warehouse ID for Genie Space")
    parser.add_argument("--profile", default=None, help="Databricks CLI profile name")
    parser.add_argument(
        "--genie-name",
        default="USDA Bee Health Data",
        help="Genie Space name (default: USDA Bee Health Data)",
    )
    parser.add_argument(
        "--ka-name",
        default="Bee Health Documents",
        help="Knowledge Assistant name (default: Bee Health Documents)",
    )
    parser.add_argument(
        "--volume",
        default="guidance_docs",
        help="UC Volume name for documents (default: guidance_docs)",
    )

    args = parser.parse_args()

    # Initialize Databricks client
    print(f"Connecting to Databricks (profile: {args.profile or 'default'})...")
    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()

    print("\n" + "="*60)
    print("CREATING AGENTS FOR BEE POLLINATOR DEMO")
    print("="*60)

    # Create Genie Space
    genie_id = create_genie_space(
        w, args.catalog, args.schema, args.warehouse_id, args.genie_name
    )

    # Create Knowledge Assistant
    ka_id = create_knowledge_assistant(
        w, args.catalog, args.schema, args.volume, args.ka_name
    )

    # Print Supervisor instructions
    print_supervisor_instructions(args.genie_name, args.ka_name)

    # Summary
    print("\n" + "="*60)
    print("AGENT SETUP COMPLETE")
    print("="*60)

    print(f"\n✓ Genie Space ready: {genie_id}")
    print(f"✓ Knowledge Assistant ready: {ka_id}")
    print("✓ Supervisor instructions printed")
    print("\nNext steps:")
    print("1. Create Supervisor Agent manually (see instructions above)")
    print("2. Wait for Knowledge Assistant indexing to complete")
    print("3. Test the demo with verification queries")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
