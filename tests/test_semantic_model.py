"""Tests for the semantic model data structures and YAML loading."""

from __future__ import annotations

import pytest

from finch_epm.engine.semantic import (
    CalculatedFieldSpec,
    EntitySpec,
    MeasureSpec,
    RelationshipSpec,
    SemanticModel,
    load_semantic_model_string,
)

SAMPLE_YAML = """
name: Financial Model
description: Core financial entities

entities:
  - name: transaction
    display_name: GL Transaction
    physical_table: fake__gl_detail
    measures:
      - name: total_amount
        display_name: Total Amount
        expression: "SUM(CAST(amount AS DOUBLE))"
        format: currency
      - name: count
        display_name: Transaction Count
        expression: "COUNT(*)"
    calculated_fields:
      - name: fiscal_year
        display_name: Fiscal Year
        expression: "SUBSTRING(period, 1, 4)"
    columns: [period, subsidiary_id, account_id, account_type, amount]

  - name: subsidiary
    display_name: Subsidiary
    physical_table: fake__subsidiary
    columns: [id, name, parent_id]

relationships:
  - name: transaction_to_subsidiary
    from_entity: transaction
    from_column: subsidiary_id
    to_entity: subsidiary
    to_column: id
    join_type: LEFT
"""


class TestLoadSemanticModel:
    def test_basic_load(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        assert model.name == "Financial Model"
        assert len(model.entities) == 2
        assert len(model.relationships) == 1

    def test_entity_lookup(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        tx = model.get_entity("transaction")
        assert tx is not None
        assert tx.physical_table == "fake__gl_detail"
        assert len(tx.measures) == 2

    def test_entity_not_found(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        assert model.get_entity("nonexistent") is None

    def test_measure_lookup(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        m = model.get_measure("transaction", "total_amount")
        assert m is not None
        assert "SUM" in m.expression
        assert m.format == "currency"

    def test_measure_not_found(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        assert model.get_measure("transaction", "nonexistent") is None
        assert model.get_measure("nonexistent", "total_amount") is None

    def test_calculated_field(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        tx = model.get_entity("transaction")
        assert tx is not None
        cf = tx.get_calculated_field("fiscal_year")
        assert cf is not None
        assert "SUBSTRING" in cf.expression

    def test_relationship_lookup(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        rel = model.get_relationship("transaction", "subsidiary")
        assert rel is not None
        assert rel.join_type == "LEFT"

    def test_relationship_reverse_lookup(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        rel = model.get_relationship("subsidiary", "transaction")
        assert rel is not None

    def test_relationship_not_found(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        assert model.get_relationship("transaction", "nonexistent") is None


class TestJoinPathResolution:
    def test_single_entity_no_joins(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        path = model.resolve_join_path(["transaction"])
        assert path == []

    def test_two_entities(self) -> None:
        model = load_semantic_model_string(SAMPLE_YAML)
        path = model.resolve_join_path(["transaction", "subsidiary"])
        assert len(path) == 1
        assert path[0].name == "transaction_to_subsidiary"

    def test_no_relationship_raises(self) -> None:
        model = SemanticModel(
            name="test",
            entities=[
                EntitySpec(name="a", physical_table="t1"),
                EntitySpec(name="b", physical_table="t2"),
            ],
            relationships=[],
        )
        with pytest.raises(ValueError, match="No relationship connects"):
            model.resolve_join_path(["a", "b"])
