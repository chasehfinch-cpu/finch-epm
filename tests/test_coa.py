"""Tests for the Chart of Accounts engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from finch_epm.engine.coa import AccountMapping, ChartOfAccounts, PLRow


class TestChartOfAccounts:
    def test_roundtrip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "coa.yaml"
        coa = ChartOfAccounts(
            level_names=["level1", "level2"],
            accounts={
                "4000": AccountMapping(
                    account_id="4000",
                    account_name="Revenue",
                    levels={"level1": "Patient Revenue", "level2": "Total Revenue"},
                    category="revenue",
                    sign_convention=-1,
                ),
            },
        )
        coa.save(path)
        loaded = ChartOfAccounts.load(path)
        assert len(loaded.accounts) == 1
        assert loaded.accounts["4000"].account_name == "Revenue"
        assert loaded.accounts["4000"].category == "revenue"
        assert loaded.level_names == ["level1", "level2"]

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        coa = ChartOfAccounts.load(tmp_path / "missing.yaml")
        assert len(coa.accounts) == 0

    def test_from_accounts_auto_generate(self) -> None:
        rows = [
            {"id": "1", "acctnumber": "4000", "accttype": "Income", "fullname": "Revenue"},
            {"id": "2", "acctnumber": "5100", "accttype": "Expense", "fullname": "Labor"},
            {"id": "3", "acctnumber": "1000", "accttype": "Bank", "fullname": "Checking"},
        ]
        coa = ChartOfAccounts.from_accounts(rows)
        assert len(coa.accounts) == 3
        assert coa.accounts["1"].category == "revenue"
        assert coa.accounts["2"].category == "expense"
        assert coa.accounts["3"].category == "undetermined"
        assert len(coa.level_names) == 4

    def test_from_csv(self, tmp_path: Path) -> None:
        csv_content = "account_id,name,level1,level2,category\n"
        csv_content += "4000,Revenue,Net Revenue,Total Revenue,revenue\n"
        csv_content += "5100,Labor,MD Comp,Total Expense,expense\n"
        csv_path = tmp_path / "coa.csv"
        csv_path.write_text(csv_content)

        coa = ChartOfAccounts.from_csv(csv_path)
        assert len(coa.accounts) == 2
        assert coa.level_names == ["level1", "level2"]
        assert coa.accounts["4000"].levels["level2"] == "Total Revenue"

    def test_from_json(self, tmp_path: Path) -> None:
        import json
        data = {
            "4000": {"name": "Revenue", "level1": "Net Revenue", "level2": "Total Revenue", "category": "revenue"},
            "5100": {"name": "Labor", "level1": "MD Comp", "level2": "Total Expense", "category": "expense"},
        }
        json_path = tmp_path / "coa.json"
        json_path.write_text(json.dumps(data))

        coa = ChartOfAccounts.from_json(json_path)
        assert len(coa.accounts) == 2
        assert coa.accounts["4000"].sign_convention == -1  # Revenue flipped

    def test_count_by_category(self) -> None:
        coa = ChartOfAccounts.from_accounts([
            {"id": "1", "accttype": "Income", "fullname": "Rev"},
            {"id": "2", "accttype": "Expense", "fullname": "Exp1"},
            {"id": "3", "accttype": "Expense", "fullname": "Exp2"},
            {"id": "4", "accttype": "Bank", "fullname": "Cash"},
        ])
        counts = coa.count_by_category()
        assert counts["revenue"] == 1
        assert counts["expense"] == 2
        assert counts["undetermined"] == 1

    def test_find_unmapped(self) -> None:
        coa = ChartOfAccounts.from_accounts([
            {"id": "1", "accttype": "Income", "fullname": "Rev"},
            {"id": "2", "accttype": "Bank", "fullname": "Cash"},
        ])
        unmapped = coa.find_unmapped()
        assert len(unmapped) == 1
        assert unmapped[0].account_id == "2"

    def test_template_import(self) -> None:
        template_path = Path(__file__).parent.parent / "examples" / "coa_template.yaml"
        if template_path.exists():
            coa = ChartOfAccounts.load(template_path)
            assert len(coa.accounts) > 0
            assert len(coa.level_names) == 4
            counts = coa.count_by_category()
            assert "revenue" in counts
            assert "expense" in counts


class TestPLTree:
    def test_build_simple_pl(self) -> None:
        coa = ChartOfAccounts(
            level_names=["level1"],
            accounts={
                "1": AccountMapping("1", "Revenue", {"level1": "Revenue"}, "revenue", -1),
                "2": AccountMapping("2", "Expense", {"level1": "Expense"}, "expense", 1),
            },
        )
        gl = {"1": -500000.0, "2": 300000.0}
        rows = coa.build_pl_tree(gl)
        assert any(r.label == "Total Revenue" for r in rows)
        assert any(r.label == "EBITDA" for r in rows)

    def test_build_hierarchical_pl(self) -> None:
        coa = ChartOfAccounts(
            level_names=["level1", "level2", "level3"],
            accounts={
                "1": AccountMapping("1", "Patient Rev", {"level1": "Patient Rev", "level2": "Net Revenue", "level3": "Total Revenue"}, "revenue", -1),
                "2": AccountMapping("2", "Other Rev", {"level1": "Other Rev", "level2": "Net Revenue", "level3": "Total Revenue"}, "revenue", -1),
                "3": AccountMapping("3", "Labor", {"level1": "Labor", "level2": "Direct", "level3": "Total Expense"}, "expense", 1),
            },
        )
        gl = {"1": -1000000.0, "2": -200000.0, "3": 500000.0}
        rows = coa.build_pl_tree(gl)

        labels = [r.label for r in rows]
        assert "Total Revenue" in labels
        assert "Total Expense" in labels
        assert "EBITDA" in labels

        # Check EBITDA = revenue - expense
        ebitda = next(r for r in rows if r.label == "EBITDA")
        assert ebitda.amount == 700000.0  # 1.2M rev - 500K exp

    def test_below_the_line(self) -> None:
        coa = ChartOfAccounts(
            level_names=["level1", "level2"],
            accounts={
                "1": AccountMapping("1", "Rev", {"level1": "Rev", "level2": "Total Revenue"}, "revenue", -1),
                "2": AccountMapping("2", "Interest", {"level1": "Interest", "level2": "BTL"}, "below-the-line", 1, True, "subtract"),
            },
        )
        gl = {"1": -1000000.0, "2": 50000.0}
        rows = coa.build_pl_tree(gl)
        assert any(r.label == "Net Income" for r in rows)
        net = next(r for r in rows if r.label == "Net Income")
        assert net.amount == 950000.0  # 1M EBITDA - 50K interest

    def test_empty_gl_data(self) -> None:
        coa = ChartOfAccounts.from_accounts([
            {"id": "1", "accttype": "Income", "fullname": "Rev"},
        ])
        rows = coa.build_pl_tree({})
        assert len(rows) > 0  # Should still produce structure


class TestTableLinker:
    def test_roundtrip_save_load(self, tmp_path: Path) -> None:
        from finch_epm.engine.table_linker import TableLinker

        linker = TableLinker()
        linker.add_link("Location", "id", "dbo__RCMSiteMaster", "Division",
                         name="loc_to_rcm", description="NS Location -> SQL RCM")
        linker.add_dimension(
            name="location",
            dimension_table="Location",
            id_column="id",
            label_column="name",
            fact_join_column="location",
            rollup_columns=["name", "subsidiary"],
        )
        path = linker.save(tmp_path / "links.yaml")

        loaded = TableLinker.load(path)
        assert len(loaded.links) == 1
        assert loaded.links[0].name == "loc_to_rcm"
        assert len(loaded.dimensions) == 1
        assert loaded.dimensions[0].name == "location"

    def test_get_join_sql(self) -> None:
        from finch_epm.engine.table_linker import TableLinker

        linker = TableLinker()
        linker.add_link("Location", "id", "dbo__RCMSiteMaster", "Division")
        sql = linker.get_join_sql("Location", "dbo__RCMSiteMaster")
        assert "LEFT JOIN" in sql
        assert "Location.id" in sql
        assert "dbo__RCMSiteMaster.Division" in sql

    def test_detect_linkable_columns(self) -> None:
        from finch_epm.engine.table_linker import TableLinker

        source_cols = [{"column_name": "id"}, {"column_name": "location"}, {"column_name": "name"}]
        target_cols = [{"column_name": "Division"}, {"column_name": "location"}, {"column_name": "SiteName"}]
        suggestions = TableLinker.detect_linkable_columns(source_cols, target_cols)
        # "location" should match exactly
        exact = [s for s in suggestions if s["match_type"] == "exact_name"]
        assert any(s["source_column"] == "location" for s in exact)

    def test_no_duplicate_links(self) -> None:
        from finch_epm.engine.table_linker import TableLinker

        linker = TableLinker()
        linker.add_link("A", "id", "B", "aid")
        linker.add_link("A", "id", "B", "aid")  # duplicate
        assert len(linker.links) == 1
