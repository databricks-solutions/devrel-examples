# Conference Booth Setup Guide — Bee Pollinator Demo

**Target Setup Time:** 15 minutes
**Skill Level:** Databricks workspace user (no admin required)

This guide walks conference booth staff through deploying the Bee Colony Health Supervisor Agent demo from scratch.

---

## Prerequisites

### Workspace Access
- [ ] Databricks workspace with Unity Catalog enabled
- [ ] Workspace user or contributor permissions
- [ ] SQL Warehouse ID (Serverless or provisioned)

### Local Setup
- [ ] Databricks CLI v0.218+ installed (`databricks --version`)
- [ ] CLI profile authenticated (`databricks auth login`)
- [ ] Clone this repository: `git clone <repo-url>`
- [ ] Navigate to: `cd demos/bee-pollinator`

### Optional
- [ ] USDA NASS QuickStats API key for live data refresh (free: https://quickstats.nass.usda.gov/api)
  - **Not required** — demo ships with pre-generated data snapshots and vendored PDFs

---

## Automated Deployment (Steps 1-2)

### Step 1: Deploy the Bundle (2 minutes)

```bash
databricks bundle deploy \
  --var="catalog=your_catalog" \
  --var="warehouse_id=your_warehouse_id"
```

Add `--profile your_profile` if not using the default profile.

### Step 2: Run the Setup Job (5 minutes)

```bash
databricks bundle run setup_demo \
  --var="catalog=your_catalog" \
  --var="warehouse_id=your_warehouse_id"
```

**What this does (two tasks, fully automated):**

1. **`load_data`** — Creates UC schema + volume, loads 3 CSV snapshots into Delta tables, uploads 4 PDFs to the volume
2. **`create_agents`** — Creates a Genie Space (`USDA Bee Health Data`) and a Knowledge Assistant (`Bee Health Documents`) via the Databricks SDK

**Expected output:**
```
"[dev ...] bee-pollinator-setup" TERMINATED SUCCESS
```

### Step 3: Confirm Resources Are Ready (3 minutes)

1. Navigate to **Data** → find `your_catalog` → `your_schema`
2. Confirm 3 tables exist (`honey_production`, `colony_loss`, `colony_stressors`)
3. Confirm `guidance_docs` volume has 4 PDFs
4. Open **Genie** and confirm `USDA Bee Health Data` exists
5. Open **Agents** and confirm `Bee Health Documents` exists
6. Wait for Knowledge Assistant indexing to finish (usually 1-3 minutes)

**Smoke tests:**
- Genie: Ask `What are the top 5 states by honey production in 2024?`
- Knowledge Assistant: Ask `What does the Varroa Management Guide recommend for monitoring mite levels?`

---

## Manual Step: Create Supervisor Agent (Step 4, ~5 minutes)

**Why manual?** Supervisor Agent has no API yet (as of March 2026). Must use UI.

1. Navigate to **AI Playground** → **Agents** (or **"Agents"** in left sidebar)
2. Click **"Create Supervisor Agent"** (or "+ New" → "Supervisor Agent")
3. **Name:** `Bee Colony Health Advisor`
4. **Description:** `Routes questions between USDA bee data and beekeeping guidance`
5. **Add Tools/Agents:**
   - Click **"Add Agent"**
   - Select **`USDA Bee Health Data`** (Genie Space created in Step 2)
   - Click **"Add Agent"** again
   - Select **`Bee Health Documents`** (Knowledge Assistant created in Step 2)
6. **Supervisor Instructions:** Paste this:

```
You are a bee colony health and pollinator conservation advisor. You help beekeepers, farmers, and agricultural extension agents by combining USDA data analysis with expert guidance from beekeeping and conservation documents.

**Route questions as follows:**

1. **Data/Statistics Questions → Genie Space (USDA Bee Health Data)**
   - Questions about honey production, colony counts, trends over time
   - Questions about colony loss rates, stressors by state/year
   - Examples:
     • "Which states had highest colony loss in 2023?"
     • "Show honey production trends in California over last 5 years"
     • "What is the average price per lb of honey in 2024?"

2. **Guidance/Best Practices Questions → Knowledge Assistant (Bee Health Documents)**
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
```

7. Click **"Save"** or **"Deploy"**

---

## Step 5: Verify the Demo (5 minutes)

Run these test queries in the Supervisor Agent to confirm everything works:

**Test 1: Data Query (should route to Genie)**
```
Which 5 states had the highest colony loss rates in 2023?
```

Expected: Table showing states like California, Montana, Florida with loss percentages.

**Test 2: Document Query (should route to Knowledge Assistant)**
```
What does the Varroa Management Guide recommend for monitoring mite levels?
```

Expected: Citations about alcohol wash, sugar roll methods, treatment thresholds.

**Test 3: Cross-Modal Query (should use BOTH agents)**
```
California lost 35% of colonies in 2023. What varroa management practices should California beekeepers prioritize?
```

Expected:
- First, data from Genie confirming CA loss rate
- Then, varroa management protocols from KA
- Synthesized recommendation connecting the two

---

## Troubleshooting

### Issue: `bundle run` fails on `load_data` task
**Solution:**
- Check that the catalog exists and you have write permissions
- Verify the bundle deployed: `databricks workspace ls "/Workspace/Users/<you>/.bundle/bee-pollinator-demo/dev/files/data/snapshots"`

### Issue: `bundle run` fails on `create_agents` task
**Solution:**
- If "No module named knowledgeassistants": the serverless SDK is too old. Try bumping `databricks-sdk>=0.44.0` in `databricks.yml`
- If Genie API validation error: lists in the serialized space must be sorted by `id`/`identifier`

### Issue: "Table not found" in Genie
**Solution:**
- Verify tables exist: `Data` → `your_catalog` → `your_schema`
- Re-run `databricks bundle run setup_demo`
- Check table permissions (need at least SELECT)

### Issue: Knowledge Assistant returns "No relevant documents found"
**Solution:**
- Verify PDFs uploaded: check the `guidance_docs` volume in the Data browser
- Wait for indexing to complete (check KA settings for indexing status)

### Issue: Supervisor Agent doesn't route correctly
**Solution:**
- Check that both sub-agents (Genie + KA) are added to Supervisor
- Verify Supervisor Instructions are pasted correctly
- Test sub-agents individually first (Genie and KA should work on their own)

---

## Post-Setup: Prepare for Booth

1. **Bookmark the Supervisor Agent** in your browser
2. **Clear conversation history** before each demo (use Reset button)
3. **Pre-load test queries** in a doc for quick copy-paste
4. **Note the MLflow experiment URL** for showing traces (see DEMO_GUIDE.md)
5. **Test on conference WiFi** if possible (verify latency is acceptable)

---

## Quick Reference

**Deployment:**
```bash
databricks bundle deploy --var="catalog=X" --var="warehouse_id=Y"
databricks bundle run setup_demo --var="catalog=X" --var="warehouse_id=Y"
```

**Workspace Resources:**
- Catalog: `your_catalog`
- Schema: `bee_pollinator` (default)
- Tables: `honey_production`, `colony_loss`, `colony_stressors`
- Volume: `guidance_docs` (4 PDFs)
- Genie Space: `USDA Bee Health Data`
- Knowledge Assistant: `Bee Health Documents`
- Supervisor Agent: `Bee Colony Health Advisor` (manual)

**Next:** See `DEMO_GUIDE.md` for the 5-minute booth demo flow.
