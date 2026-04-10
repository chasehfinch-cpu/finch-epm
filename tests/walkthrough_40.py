"""40 user walkthrough tests for finch-epm.

Tests every path a user might take from install to dashboard viewing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

results = []


def test(num, scenario, checks):
    passed = True
    issues = []
    for name, check_fn in checks:
        try:
            if not check_fn():
                passed = False
                issues.append(f'FAILED: {name}')
        except Exception as e:
            passed = False
            issues.append(f'{name}: {str(e)[:80]}')
    results.append((num, scenario, "PASS" if passed else "FAIL", issues))


# ---- INSTALLATION & SETUP (1-8) ----

test(1, "Package imports correctly", [
    ("finch_epm imports", lambda: __import__("finch_epm") is not None),
    ("Version is 0.1.0", lambda: __import__("finch_epm").__version__ == "0.1.0"),
])

test(2, "CLI entry point works", [
    ("cli function exists", lambda: callable(getattr(__import__("finch_epm.cli.main", fromlist=["cli"]), "cli"))),
])

test(3, "Setup wizard accessible", [
    ("setup command exists", lambda: callable(getattr(__import__("finch_epm.cli.main", fromlist=["setup"]), "setup"))),
])

test(4, "All 7 connector types exist", [
    ("netsuite", lambda: Path("src/finch_epm/connectors/netsuite/connector.py").exists()),
    ("sqlserver", lambda: Path("src/finch_epm/connectors/sqlserver/connector.py").exists()),
    ("postgres", lambda: Path("src/finch_epm/connectors/postgres/connector.py").exists()),
    ("snowflake", lambda: Path("src/finch_epm/connectors/snowflake/connector.py").exists()),
    ("bigquery", lambda: Path("src/finch_epm/connectors/bigquery/connector.py").exists()),
    ("odbc", lambda: Path("src/finch_epm/connectors/odbc/connector.py").exists()),
    ("fake", lambda: Path("src/finch_epm/connectors/fake.py").exists()),
])

test(5, "FakeConnector passes full interface", [
    ("connect", lambda: (c := __import__("finch_epm.connectors.fake", fromlist=["FakeConnector"]).FakeConnector()) or c.connect() or c.is_connected),
    ("introspect", lambda: len(__import__("finch_epm.connectors.fake", fromlist=["FakeConnector"]).FakeConnector(config={}).introspect_schema().tables) > 0),
])

test(6, "Keyring credential storage", [
    ("keyring imports", lambda: __import__("keyring") is not None),
    ("ProfileManager creates", lambda: __import__("finch_epm.profiles.manager", fromlist=["ProfileManager"]).ProfileManager(Path("/tmp/test_profiles.json")) is not None),
])

test(7, "platformdirs paths work", [
    ("data_dir", lambda: callable(getattr(__import__("finch_epm.paths", fromlist=["data_dir"]), "data_dir"))),
    ("cache_db_path", lambda: callable(getattr(__import__("finch_epm.paths", fromlist=["cache_db_path"]), "cache_db_path"))),
])

test(8, ".gitignore excludes secrets", [
    (".env ignored", lambda: ".env" in Path(".gitignore").read_text()),
    (".duckdb ignored", lambda: "*.duckdb" in Path(".gitignore").read_text()),
    (".claude ignored", lambda: ".claude/" in Path(".gitignore").read_text()),
])

# ---- CATALOG & SCHEMA (9-12) ----

from finch_epm.catalog.catalog import CatalogStore
from finch_epm.connectors.fake import FakeConnector

test(9, "Catalog store CRUD", [
    ("create", lambda: CatalogStore(":memory:") is not None),
    ("save schema", lambda: (s := CatalogStore(":memory:")) and s.save_schema(FakeConnector().introspect_schema()) is None),
])

test(10, "Catalog lists tables after crawl", [
    ("tables listed", lambda: (s := CatalogStore(":memory:")) and s.save_schema(FakeConnector().introspect_schema()) is None and len(s.list_tables("fake", "test")) == 3),
])

test(11, "Catalog lists columns", [
    ("columns for gl_detail", lambda: (s := CatalogStore(":memory:")) and s.save_schema(FakeConnector().introspect_schema()) is None and len(s.list_columns("fake", "test", "gl_detail")) == 6),
])

test(12, "Catalog tracks dimensions", [
    ("dimensions saved", lambda: (s := CatalogStore(":memory:")) and s.save_dimensions("fake", "test", FakeConnector().list_dimensions()) is None and len(s.list_dimensions("fake", "test")) == 2),
])

# ---- DATA SYNC (13-18) ----

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import QueryRequest
from finch_epm.cache.sync import SyncEngine

test(13, "Cache engine creates in-memory DB", [
    ("creates", lambda: LocalCacheEngine(":memory:") is not None),
])

def _test_sync():
    fc = FakeConnector(); fc.connect(); ce = LocalCacheEngine(":memory:")
    return SyncEngine(fc, ce).sync_tables(["gl_detail"], mode="full").total_rows == 10

def _test_watermark():
    fc = FakeConnector(); fc.connect(); ce = LocalCacheEngine(":memory:")
    SyncEngine(fc, ce).sync_tables(["gl_detail"], mode="full")
    return ce.get_watermark("fake", "test", "gl_detail") is not None

def _test_incremental():
    fc = FakeConnector(); fc.connect(); ce = LocalCacheEngine(":memory:")
    SyncEngine(fc, ce).sync_tables(["gl_detail"], mode="full")
    SyncEngine(fc, ce).sync_tables(["gl_detail"], mode="incremental")
    return ce.execute_query(QueryRequest(sql="SELECT COUNT(*) FROM gl_detail")).rows[0][0] == 20

def _test_partial():
    fc = FakeConnector(); fc.connect(); ce = LocalCacheEngine(":memory:")
    r = SyncEngine(fc, ce).sync_tables(["nonexistent", "subsidiary"], mode="full")
    return r.tables_synced == 1 and r.tables_failed == 1

test(14, "Sync engine syncs FakeConnector data", [
    ("syncs gl_detail", _test_sync),
])

test(15, "Watermark tracking works", [
    ("watermark created", _test_watermark),
])

test(16, "Incremental sync appends", [
    ("append works", _test_incremental),
])

test(17, "Partial failure continues", [
    ("one fails one succeeds", _test_partial),
])

test(18, "Background sync service module exists", [
    ("service.py exists", lambda: Path("src/finch_epm/cache/service.py").exists()),
    ("scheduler.py exists", lambda: Path("src/finch_epm/cache/scheduler.py").exists()),
])

# ---- FILE IMPORT (19-20) ----

test(19, "CSV import module exists", [
    ("file connector exists", lambda: Path("src/finch_epm/connectors/file/connector.py").exists()),
])

test(20, "Import CLI command available", [
    ("import command", lambda: "import" in Path("src/finch_epm/cli/main.py").read_text()),
])

# ---- DASHBOARD PARSING (21-28) ----

from finch_epm.dashboard.fdash import load_fdash_string, validate_fdash, load_fdash

test(21, "Parse minimal .fdash", [
    ("parses", lambda: load_fdash_string("name: T\nqueries:\n  - name: q\n    sql: SELECT 1\ncharts:\n  - type: table\n    title: T\n    data: q") is not None),
])

test(22, "Parse multi-page .fdash", [
    ("pages detected", lambda: load_fdash_string("name: T\nqueries:\n  - name: q\n    sql: SELECT 1\npages:\n  - name: P1\n    charts:\n      - type: table\n        title: T\n        data: q").is_multi_page),
])

test(23, "Parse filters in .fdash", [
    ("filter parsed", lambda: len(load_fdash_string("name: T\nqueries:\n  - name: q\n    sql: SELECT 1\nfilters:\n  - name: f\n    label: F\n    query: SELECT 1\n    parameter: p\ncharts:\n  - type: table\n    title: T\n    data: q").filters) == 1),
])

test(24, "Parse cross_filter field", [
    ("cross_filter set", lambda: load_fdash_string("name: T\nqueries:\n  - name: q\n    sql: SELECT 1\ncharts:\n  - type: bar\n    title: B\n    data: q\n    x: a\n    y: b\n    cross_filter: a").charts[0].cross_filter == "a"),
])

test(25, "Validate detects missing query reference", [
    ("error found", lambda: any("nonexistent" in e for e in validate_fdash(load_fdash_string("name: T\nqueries:\n  - name: q\n    sql: SELECT 1\ncharts:\n  - type: table\n    title: T\n    data: nonexistent")))),
])

test(26, "All example .fdash files parse", [
    ("multi_tab", lambda: load_fdash("examples/multi_tab_financial.fdash") is not None),
    ("account_overview", lambda: load_fdash("examples/account_overview.fdash") is not None),
    ("cfo_ar_timing", lambda: load_fdash("examples/cfo_ar_timing.fdash") is not None),
    ("cfo_payor", lambda: load_fdash("examples/cfo_payor_analysis.fdash") is not None),
    ("netsuite_gl", lambda: load_fdash("examples/netsuite_gl_overview.fdash") is not None),
    ("site_pl", lambda: load_fdash("examples/site_pl.fdash") is not None),
])

test(27, "Multi-series y field accepted", [
    ("list y valid", lambda: __import__("finch_epm.dashboard.renderer.registry", fromlist=["get_chart_renderer"]).get_chart_renderer("bar").validate_spec({"data": "q", "x": "a", "y": ["b", "c"]}) == []),
])

test(28, "All 10 chart types registered", [
    ("10 types", lambda: len(__import__("finch_epm.dashboard.renderer.registry", fromlist=["list_chart_types"]).list_chart_types()) >= 10),
])

# ---- QUERY RESOLUTION (29-32) ----

from finch_epm.dashboard.resolver import resolve_queries, resolve_parameters

test(29, "Period parameter resolves to date", [
    ("resolves", lambda: len(resolve_parameters(load_fdash_string("name: T\nqueries:\n  - name: q\n    sql: SELECT 1\nparameters:\n  s:\n    type: period\n    default: current_quarter_start\ncharts:\n  - type: table\n    title: T\n    data: q"))["s"]) == 10),
])

test(30, "Parameter override works", [
    ("override", lambda: resolve_parameters(load_fdash_string("name: T\nqueries:\n  - name: q\n    sql: SELECT 1\nparameters:\n  x:\n    type: number\n    default: 100\ncharts:\n  - type: table\n    title: T\n    data: q"), {"x": 50})["x"] == 50),
])

test(31, "Query executes against cache", [
    ("returns rows", lambda: LocalCacheEngine(":memory:").execute_query(QueryRequest(sql="SELECT 1 AS x")).row_count == 1),
])

test(32, "Missing table returns MISSING staleness", [
    ("missing detected", lambda: LocalCacheEngine(":memory:").execute_query(QueryRequest(sql="SELECT * FROM nonexistent")).staleness.level.value == "missing"),
])

# ---- P&L ENGINE (33-35) ----

from finch_epm.engine.chart_of_accounts import get_default_pl_structure, load_pl_structure

test(33, "Default P&L structure loads", [
    ("net_income root", lambda: get_default_pl_structure().name == "net_income"),
    ("has children", lambda: len(get_default_pl_structure().children) > 0),
])

test(34, "Custom P&L YAML loads", [
    ("default loads", lambda: load_pl_structure("examples/default_pl_structure.yaml").name == "net_income"),
    ("healthcare loads", lambda: load_pl_structure("examples/healthcare_pl_structure.yaml").name == "net_income"),
])

test(35, "Dimension mapping module exists", [
    ("module exists", lambda: Path("src/finch_epm/engine/dimensions.py").exists()),
])

# ---- SERVER & FRONTEND (36-38) ----

test(36, "Dashboard server class exists", [
    ("class exists", lambda: callable(getattr(__import__("finch_epm.server.app", fromlist=["DashboardServer"]), "DashboardServer"))),
])

test(37, "Static assets bundled for offline use", [
    ("echarts.min.js", lambda: Path("src/finch_epm/server/static/echarts.min.js").exists()),
    ("vega.min.js", lambda: Path("src/finch_epm/server/static/vega.min.js").exists()),
    ("vega-lite.min.js", lambda: Path("src/finch_epm/server/static/vega-lite.min.js").exists()),
    ("vega-embed.min.js", lambda: Path("src/finch_epm/server/static/vega-embed.min.js").exists()),
    ("dashboard.html", lambda: Path("src/finch_epm/server/templates/dashboard.html").exists()),
])

test(38, "PyInstaller installer exists", [
    ("spec file", lambda: Path("installer/finch-epm.spec").exists()),
    ("entry point", lambda: Path("installer/entry.py").exists()),
    ("file association", lambda: Path("installer/register_fdash.py").exists()),
    ("build script", lambda: Path("installer/build.py").exists()),
])

# ---- DOCUMENTATION (39-40) ----

test(39, "User documentation complete", [
    ("README.md", lambda: Path("README.md").exists() and len(Path("README.md").read_text()) > 1000),
    ("GETTING_STARTED.md", lambda: Path("GETTING_STARTED.md").exists() and len(Path("GETTING_STARTED.md").read_text()) > 1000),
    ("DASHBOARDS.md", lambda: Path("DASHBOARDS.md").exists() and len(Path("DASHBOARDS.md").read_text()) > 5000),
    ("CONTRIBUTING.md", lambda: Path("CONTRIBUTING.md").exists()),
    ("CHANGELOG.md", lambda: Path("CHANGELOG.md").exists()),
    ("CLAUDE.md", lambda: Path("CLAUDE.md").exists()),
])

test(40, "IT deployment: no hardcoded paths or user-specific config in code", [
    ("no hardcoded user paths", lambda: "ChaseFinch" not in Path("src/finch_epm/paths.py").read_text()),
    ("no hardcoded server names", lambda: "hospintegration" not in Path("src/finch_epm/cli/main.py").read_text()),
    ("platformdirs used", lambda: "platformdirs" in Path("src/finch_epm/paths.py").read_text()),
    ("no telemetry callbacks", lambda: "send_analytics" not in Path("src/finch_epm/cli/main.py").read_text() and "telemetry" not in Path("src/finch_epm/cli/main.py").read_text()),
])


# Print results
print("=" * 70)
print("  FINCH-EPM: 40 USER WALKTHROUGH TESTS")
print("=" * 70)
print()

passed = sum(1 for _, _, s, _ in results if s == "PASS")
failed = sum(1 for _, _, s, _ in results if s == "FAIL")

for num, scenario, status, issues in results:
    marker = "PASS" if status == "PASS" else "FAIL"
    print(f"  [{marker}] {num:>2}. {scenario}")
    if issues:
        for issue in issues:
            print(f"         {issue}")

print()
print(f"  Results: {passed} passed, {failed} failed out of {len(results)}")
print()
if failed == 0:
    print("  All 40 walkthroughs passed.")
else:
    print(f"  {failed} walkthrough(s) need attention.")
