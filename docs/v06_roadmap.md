# v0.6 Roadmap — Known Issues and Planned Improvements

Issues discovered during v0.5 development that should be addressed in the next release.

## Critical Fixes

### 1. Streaming sync for large tables
**Problem**: `fetch_facts()` loads ALL rows into a Python list before writing to cache. For 3M+ row tables (RCMPayments, RCMBillingData), this consumes 8GB+ RAM and takes 10+ minutes just for the memory allocation.

**Fix**: Implement streaming/batched sync that fetches rows in chunks (e.g., 50K at a time) and writes each chunk to cache immediately. Never hold more than one chunk in memory.

**Files**: `src/finch_epm/connectors/base.py` (add `fetch_facts_stream` interface), all connector implementations, `src/finch_epm/cache/sync.py`

**Impact**: Initial sync of 3M+ row tables drops from 10+ min to ~1 min.

### 2. Year-chunking for tables without lastmodifieddate
**Problem**: NetSuite's SuiteQL caps at 100K rows per query. The year-chunking workaround splits by `EXTRACT(YEAR FROM lastmodifieddate)`, but junction tables (TransactionAccountingLine, TransactionLine) don't have `lastmodifieddate` as a queryable field. The query returns HTTP 400.

**Result**: TAL only synced 2023-2026 data (374K of 708K rows). TransactionLine failed entirely.

**Fix**: For tables without `lastmodifieddate`, chunk by joining to the parent Transaction table's `trandate` year. Example:
```sql
SELECT tal.* FROM TransactionAccountingLine tal
JOIN Transaction t ON tal.transaction = t.id
WHERE EXTRACT(YEAR FROM t.lastmodifieddate) = 2022
```
Or chunk by `ROWID` ranges if the table supports it.

**Files**: `src/finch_epm/connectors/netsuite/connector.py` (`_fetch_by_year_chunks`)

### 3. Duplicate un-namespaced cache tables
**Problem**: Cache has both `Transaction` (old, from pre-v0.4 sync) and `ns__Transaction` (new, namespaced). Dashboard queries reference un-namespaced names but sync may write to namespaced names, causing confusion.

**Fix**: Migration script that renames old tables to namespaced format. Clean up on first v0.6 sync.

**Files**: `src/finch_epm/cache/sync.py` (migration function already exists but needs to run automatically)

## Performance Improvements

### 4. CSV COPY for all connectors
**Status**: Implemented in v0.5 for the cache write path. But the SQL Server connector's `fetch_facts` still loads everything into memory. The ODBC cursor could be iterated in batches.

### 5. Parallel table sync
**Problem**: Tables sync sequentially. For SQL Server with 15+ tables, this means waiting for each one to finish before starting the next.

**Fix**: Use `concurrent.futures.ThreadPoolExecutor` to sync multiple tables in parallel (with a configurable max_workers). Each table gets its own ODBC connection.

### 6. Progress reporting during large fetches
**Problem**: For a 3M row SQL Server table, there's no progress output during the fetch. The user sees nothing until the entire table is done.

**Fix**: The streaming sync (item 1) solves this — each batch reports progress.

## Feature Additions

### 7. Interactive table-linking web UI
Drag-and-drop interface for configuring the compilation map. Users see all tables, filter by columns, and visually connect them. Currently CLI-only.

### 8. Git-based dashboard sharing
`finch-epm pull/push` commands that treat a directory of .fdash files as a shared dashboard library backed by Git.

### 9. On-prem IT governance
Lightweight LAN-based management service:
- IT sees which machines have finch-epm installed
- Push/pull configuration (compilation map, COA, credentials) over the network
- Audit log of which users opened which dashboards
- No cloud, no internet required — runs on existing Windows Server infrastructure

### 10. Per-table sync cadence
Hot tables (updated hourly), warm tables (daily), cold tables (weekly), manual-only. Currently all tables sync at the same interval.

### 11. macOS and Linux deployment scripts
Currently only PowerShell (Windows). Need Bash/Ansible equivalents.

### 12. P&L hierarchy expand/collapse in dashboard UI
The CSS classes for 5-level hierarchy coloring exist. The JavaScript for expand/collapse (clickable parent rows, toggle children) needs to be wired into the table renderer.
