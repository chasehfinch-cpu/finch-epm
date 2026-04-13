"""Semantic layer: logical models over physical cache tables.

Defines entities (virtual tables), measures (aggregate expressions),
calculated fields, and relationships. Dashboard queries can reference
logical names instead of writing raw SQL.

The semantic model is defined in YAML (``.semantic.yml``) and loaded
at dashboard resolution time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from finch_epm.engine.dimensions import DimensionMappingSet, load_dimension_mappings


@dataclass(frozen=True)
class MeasureSpec:
    """A named aggregate SQL expression.

    Example: ``SUM(CAST(amount AS DOUBLE))`` with format ``currency``.
    """

    name: str
    display_name: str = ""
    expression: str = ""
    format: str = ""
    description: str = ""


@dataclass(frozen=True)
class CalculatedFieldSpec:
    """A non-aggregate SQL expression.

    Example: ``SUBSTRING(trandate, 1, 4)`` for fiscal year.
    """

    name: str
    display_name: str = ""
    expression: str = ""
    description: str = ""


@dataclass(frozen=True)
class RelationshipSpec:
    """Describes a JOIN between two entities."""

    name: str
    from_entity: str
    from_column: str
    to_entity: str
    to_column: str
    join_type: str = "LEFT"


@dataclass
class EntitySpec:
    """Maps a logical entity name to a physical (namespaced) cache table."""

    name: str
    display_name: str = ""
    physical_table: str = ""
    alias: str = ""
    measures: list[MeasureSpec] = field(default_factory=list)
    calculated_fields: list[CalculatedFieldSpec] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    description: str = ""

    def get_measure(self, name: str) -> MeasureSpec | None:
        for m in self.measures:
            if m.name == name:
                return m
        return None

    def get_calculated_field(self, name: str) -> CalculatedFieldSpec | None:
        for cf in self.calculated_fields:
            if cf.name == name:
                return cf
        return None

    @property
    def sql_alias(self) -> str:
        return self.alias or self.name


@dataclass
class SemanticModel:
    """Top-level semantic model: entities, relationships, and dimension mappings."""

    name: str
    description: str = ""
    entities: list[EntitySpec] = field(default_factory=list)
    relationships: list[RelationshipSpec] = field(default_factory=list)
    dimension_mappings: DimensionMappingSet | None = None

    def get_entity(self, name: str) -> EntitySpec | None:
        for e in self.entities:
            if e.name == name:
                return e
        return None

    def get_measure(self, entity_name: str, measure_name: str) -> MeasureSpec | None:
        entity = self.get_entity(entity_name)
        if entity is None:
            return None
        return entity.get_measure(measure_name)

    def get_relationship(
        self, from_entity: str, to_entity: str
    ) -> RelationshipSpec | None:
        for r in self.relationships:
            if r.from_entity == from_entity and r.to_entity == to_entity:
                return r
            if r.to_entity == from_entity and r.from_entity == to_entity:
                return r
        return None

    def resolve_join_path(
        self, entity_names: list[str]
    ) -> list[RelationshipSpec]:
        """Find relationships connecting the given entities.

        For each entity beyond the first, finds a relationship connecting
        it to any previously seen entity.

        Raises:
            ValueError: If no relationship connects an entity to the path.
        """
        if len(entity_names) <= 1:
            return []

        seen = {entity_names[0]}
        path: list[RelationshipSpec] = []

        for name in entity_names[1:]:
            found = False
            for r in self.relationships:
                if (r.from_entity in seen and r.to_entity == name) or \
                   (r.to_entity in seen and r.from_entity == name):
                    path.append(r)
                    seen.add(name)
                    found = True
                    break
            if not found:
                raise ValueError(
                    f"No relationship connects {name!r} to {sorted(seen)}"
                )

        return path


def load_semantic_model(path: str | Path) -> SemanticModel:
    """Load a semantic model from a YAML file."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _parse_semantic_model(raw, base_dir=path.parent)


def load_semantic_model_string(yaml_str: str) -> SemanticModel:
    """Load a semantic model from a YAML string (for testing)."""
    raw = yaml.safe_load(yaml_str)
    return _parse_semantic_model(raw)


def save_semantic_model(model: SemanticModel, path: str | Path) -> None:
    """Save a semantic model to a YAML file."""
    path = Path(path)
    raw = _serialize_semantic_model(model)
    path.write_text(
        yaml.dump(raw, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _parse_semantic_model(
    raw: dict[str, Any],
    base_dir: Path | None = None,
) -> SemanticModel:
    entities = []
    for e in raw.get("entities", []):
        measures = [
            MeasureSpec(
                name=m.get("name", ""),
                display_name=m.get("display_name", m.get("name", "")),
                expression=m.get("expression", ""),
                format=m.get("format", ""),
                description=m.get("description", ""),
            )
            for m in e.get("measures", [])
        ]
        calc_fields = [
            CalculatedFieldSpec(
                name=cf.get("name", ""),
                display_name=cf.get("display_name", cf.get("name", "")),
                expression=cf.get("expression", ""),
                description=cf.get("description", ""),
            )
            for cf in e.get("calculated_fields", [])
        ]
        entities.append(EntitySpec(
            name=e.get("name", ""),
            display_name=e.get("display_name", e.get("name", "")),
            physical_table=e.get("physical_table", ""),
            alias=e.get("alias", ""),
            measures=measures,
            calculated_fields=calc_fields,
            columns=e.get("columns", []),
            description=e.get("description", ""),
        ))

    relationships = [
        RelationshipSpec(
            name=r.get("name", ""),
            from_entity=r.get("from_entity", ""),
            from_column=r.get("from_column", ""),
            to_entity=r.get("to_entity", ""),
            to_column=r.get("to_column", ""),
            join_type=r.get("join_type", "LEFT"),
        )
        for r in raw.get("relationships", [])
    ]

    dim_mappings = None
    dim_path = raw.get("dimension_mappings")
    if dim_path and base_dir:
        dim_mappings = load_dimension_mappings(base_dir / dim_path)

    return SemanticModel(
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        entities=entities,
        relationships=relationships,
        dimension_mappings=dim_mappings,
    )


def _serialize_semantic_model(model: SemanticModel) -> dict[str, Any]:
    entities = []
    for e in model.entities:
        entity_dict: dict[str, Any] = {
            "name": e.name,
            "display_name": e.display_name,
            "physical_table": e.physical_table,
        }
        if e.alias:
            entity_dict["alias"] = e.alias
        if e.measures:
            entity_dict["measures"] = [
                {"name": m.name, "display_name": m.display_name,
                 "expression": m.expression, "format": m.format}
                for m in e.measures
            ]
        if e.calculated_fields:
            entity_dict["calculated_fields"] = [
                {"name": cf.name, "display_name": cf.display_name,
                 "expression": cf.expression}
                for cf in e.calculated_fields
            ]
        if e.columns:
            entity_dict["columns"] = e.columns
        entities.append(entity_dict)

    relationships = [
        {"name": r.name, "from_entity": r.from_entity, "from_column": r.from_column,
         "to_entity": r.to_entity, "to_column": r.to_column, "join_type": r.join_type}
        for r in model.relationships
    ]

    return {
        "name": model.name,
        "description": model.description,
        "entities": entities,
        "relationships": relationships,
    }
