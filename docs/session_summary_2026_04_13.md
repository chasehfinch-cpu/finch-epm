# Session Summary — April 13, 2026

## What was built today

### 26 commits pushed to GitHub. 389 tests passing. CI green on all platforms.

### Milestone 1: LLM Layer (Complete)
- Provider-agnostic LLM abstraction with 5 providers (Anthropic, OpenAI, Google, Ollama, OpenAI-compatible)
- `finch-epm ask "prompt"` generates validated .fdash files with retry loop
- Model alias registry (fast/balanced/best)
- Multiple LLM profiles with keyring storage

### Milestone 2: MCP Server (Complete)
- 10 tools + 4 resources for Claude Desktop, Claude Code, Cursor
- SQL injection guard via sqlglot
- stdio + SSE transport

### Milestone 3: Visual Overhaul (Complete)
- 7 theme presets (modern_light, modern_dark, financial, financial_terminal, executive, wsj, monospace)
- P&L hierarchy expand/collapse with 5-level row coloring
- pl_matrix chart type (Account × Month with frozen columns)
- EBITDA bridge waterfall chart
- Toggle filter buttons
- Drill-down detail panel
- ExcelJS styled export with frozen panes and hierarchy colors
- Markdown narrative blocks
- Layout system (full/half/third/quarter)
- Print support, empty states, brand block

### Data Infrastructure (Complete)
- Full data sync with no artificial row caps
- Year-range chunking for NetSuite's 100K API limit
- Junction-table chunking for TAL/TL (via Transaction subquery)
- Quarterly split fix for junction tables
- CSV COPY bulk insert (68x faster than executemany)
- Streaming sync (fetch_facts_chunked, 50K-row batches)
- Incremental sync with deduplication
- Schema evolution (ALTER TABLE ADD COLUMN for new fields)

### Compilation Map + Mapping UI (Complete)
- Single source of truth for cross-source data linking
- Web UI at /mapping with value-based column matching
- Click a column → system finds matching values across ALL other tables
- Jaccard similarity with prefix transforms (L, D, E)
- Network share pointer for team-wide sharing
- `finch-epm map setup/show/use/import` CLI commands

### Chart of Accounts (Complete)
- Unlimited hierarchy levels
- Auto-generate from cached Account data
- Import from YAML/JSON/CSV templates
- Team sharing
- `finch-epm coa setup/import/show/edit/unmapped`

### Binary Flags (Complete)
- Auto-detect 0/1 columns (Active, Terminated, CoreFY25, etc.)
- Classify as status/period/custom
- Prompted during sync for new reference tables

### Metrics Layer (Complete)
- Cross-source calculated measures with sign normalization
- Time alignment (M/D/YYYY ↔ YYYY-MM-DD)
- Shareable YAML definitions

### Classification System (Complete)
- Schema change detection (new/removed tables and columns)
- Data classification (financial, statistical, operational, qualitative)
- Unmapped account detection against COA

### Infrastructure (Complete)
- GitHub Actions CI (pytest + ruff, Python 3.10-3.13, Ubuntu + Windows)
- PyPI publishing workflow (Trusted Publishing on tag push)
- IT deployment script (deploy.ps1, Intune/SCCM/GPO)
- Silent config bundle (finch-epm setup --config)
- Sync status visibility (dashboard banner + finch-epm status command)
- Graceful dashboard degradation for missing data

---

## Current data state

| Table | Rows | Source |
|-------|------|--------|
| ns__Transaction | 154,433 | NetSuite (all years) |
| ns__TransactionAccountingLine | 373,679 | NetSuite (2023-2026 only, re-sync needed) |
| ns__TransactionLine | 294,920 | NetSuite (2018-2022, re-sync needed for 2023+) |
| Account | 649 | NetSuite |
| Subsidiary | 17 | NetSuite |
| Location | 128 | NetSuite |
| Department | 36 | NetSuite |
| ss__dbo__IFSLocations | 123 | SQL Server financedw |
| ss__dbo__IFSDepartments | 49 | SQL Server financedw |
| ss__dbo__IFSEntities | 18 | SQL Server financedw |
| ss__dbo__WaterFallT2 | 874,093 | SQL Server azure |
| ss__dbo__RCMCashData | 401,192 | SQL Server azure |
| ss__dbo__RCMPayments | 1,251,611 | SQL Server azure |
| + 19 more tables | ~200K | Various |
| **TOTAL** | **~3.7M** | |

---

## Known issues for tomorrow

### 1. TAL/TL incomplete sync
TransactionAccountingLine has 2023-2026 only (374K of 708K). TransactionLine has 2018-2022 only (295K of 708K). Both need a re-sync with the fixed quarterly chunking code (committed but not yet run). One more sync cycle will get the full data.

### 2. Compilation map not yet created for your data
The mapping UI and CLI are built, but nobody has actually run through the setup to link IFSLocations → TransactionLine.location, IFSDepartments → TransactionLine.department, etc. This needs to happen before dashboard filters work fully.

### 3. Resolver auto-JOIN not yet wired
The compilation map can generate JOIN SQL, but the resolver doesn't yet automatically inject it. Dashboard queries still hardcode JOINs. Need to enhance `_inject_linked_joins` to use the compilation map's hub-spoke model.

### 4. Dashboard queries reference wrong table names
The financial_reports.fdash was updated to use ns__ tables and Subsidiary joins, but the IFS location/department filters were removed because TransactionLine data was incomplete. Once TL is fully synced, these filters should be re-added.

### 5. Large table sync memory (v0.6)
Tables over 1M rows (RCMPayments at 3M) still load all rows into memory during ODBC fetch. The streaming sync fixes the cache write but not the connector fetch. v0.6 should add batched ODBC fetching.

---

## What to do tomorrow

1. **Re-sync TAL + TL** with the fixed quarterly chunking code (one command, ~60 min)
2. **Run `finch-epm map setup`** to create the compilation map linking IFS tables to NS/SQL data
3. **Test the mapping UI** at /mapping — click LocationID, see the matches
4. **Wire the auto-JOIN resolver** so dashboard queries don't need manual JOINs
5. **Rebuild the financial_reports.fdash** with IFS-driven filters now that TL has dimension data
6. **Verify end-to-end**: open the dashboard, switch years, filter by group/location/entity
7. **Build `finch-epm health`** command showing mapping coverage

---

## v0.6 roadmap (documented in docs/v06_roadmap.md)

1. Streaming ODBC fetch for 3M+ row tables
2. Full lastmodifieddate fix (junction table quarterly split — done in v0.5)
3. Parallel table sync
4. Interactive table-linking web UI improvements
5. Git-based dashboard sharing
6. On-prem IT governance (LAN-based)
7. Per-table sync cadence
8. macOS/Linux deployment scripts
9. Metrics layer integration into resolver
10. P&L hierarchy expand/collapse visual polish
