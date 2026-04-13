"""SQL query builder from semantic model references.

Generates DuckDB SQL from logical entity/measure/group_by names defined
in a :class:`SemanticModel`. Resolves JOINs from relationships and
expands measures into their SQL expressions.
"""

from __future__ import annotations

from typing import Any

from finch_epm.engine.semantic import SemanticModel


class SemanticQueryBuilder:
    """Builds SQL from semantic model references.

    Usage::

        builder = SemanticQueryBuilder(model)
        sql = builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount"],
            group_by=["location.GroupRollup"],
        )
    """

    def __init__(self, model: SemanticModel) -> None:
        self._model = model

    def build_query(
        self,
        entities: list[str],
        measures: list[str] | None = None,
        group_by: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        limit: int | None = None,
    ) -> str:
        """Build a SQL query from semantic references.

        Args:
            entities: Primary entity names (first is the FROM table).
            measures: ``"entity.measure"`` dot-notation references.
            group_by: ``"entity.column"`` or ``"entity.calculated_field"``
                dot-notation references.
            filters: ``{"entity.column": value}`` filter dict.
            order_by: Column references for ORDER BY.
            limit: Row limit.

        Returns:
            Complete DuckDB SQL string.

        Raises:
            ValueError: If any referenced entity, measure, or column
                is not found in the model.
        """
        measures = measures or []
        group_by = group_by or []
        filters = filters or {}
        order_by = order_by or []

        # Collect all entities referenced across measures, group_by, and filters
        all_entity_names = list(entities)
        for ref in measures + group_by + order_by + list(filters.keys()):
            if "." in ref:
                entity_name = ref.split(".")[0]
                if entity_name not in all_entity_names:
                    all_entity_names.append(entity_name)

        # Validate entities exist
        entity_map: dict[str, Any] = {}
        for name in all_entity_names:
            entity = self._model.get_entity(name)
            if entity is None:
                raise ValueError(f"Entity {name!r} not found in semantic model")
            entity_map[name] = entity

        # Primary entity (FROM)
        primary = entity_map[all_entity_names[0]]

        # Resolve JOINs
        joins = self._model.resolve_join_path(all_entity_names)

        # Build SELECT columns
        select_parts: list[str] = []
        group_by_parts: list[str] = []

        for ref in group_by:
            col_sql = self._resolve_column_ref(ref, entity_map)
            col_name = ref.split(".")[-1]
            select_parts.append(f"{col_sql} AS {col_name}")
            group_by_parts.append(col_sql)

        for ref in measures:
            entity_name, measure_name = ref.split(".", 1)
            entity = entity_map[entity_name]
            measure = entity.get_measure(measure_name)
            if measure is None:
                raise ValueError(
                    f"Measure {measure_name!r} not found on entity {entity_name!r}"
                )
            select_parts.append(f"{measure.expression} AS {measure.name}")

        if not select_parts:
            select_parts.append("*")

        # Build FROM + JOINs
        from_clause = f"{primary.physical_table} {primary.sql_alias}"
        join_clauses: list[str] = []
        for rel in joins:
            from_ent = entity_map[rel.from_entity]
            to_ent = entity_map[rel.to_entity]
            # Determine which side is already in the FROM/JOIN chain
            if rel.from_entity in {all_entity_names[0]} | {
                j.to_entity for j in join_clauses[:joins.index(rel)]
            } if join_clauses else rel.from_entity == all_entity_names[0]:
                join_clauses.append(
                    f"{rel.join_type} JOIN {to_ent.physical_table} {to_ent.sql_alias} "
                    f"ON {from_ent.sql_alias}.{rel.from_column} = "
                    f"{to_ent.sql_alias}.{rel.to_column}"
                )
            else:
                join_clauses.append(
                    f"{rel.join_type} JOIN {from_ent.physical_table} {from_ent.sql_alias} "
                    f"ON {to_ent.sql_alias}.{rel.to_column} = "
                    f"{from_ent.sql_alias}.{rel.from_column}"
                )

        # Build WHERE
        where_parts: list[str] = []
        for ref, value in filters.items():
            col_sql = self._resolve_column_ref(ref, entity_map)
            if isinstance(value, (int, float)):
                where_parts.append(f"{col_sql} = {value}")
            elif value is None:
                where_parts.append(f"{col_sql} IS NULL")
            else:
                escaped = str(value).replace("'", "''")
                where_parts.append(f"{col_sql} = '{escaped}'")

        # Build ORDER BY
        order_parts: list[str] = []
        for ref in order_by:
            order_parts.append(self._resolve_column_ref(ref, entity_map))

        # Assemble SQL
        sql = f"SELECT {', '.join(select_parts)}\nFROM {from_clause}"
        for jc in join_clauses:
            sql += f"\n{jc}"
        if where_parts:
            sql += f"\nWHERE {' AND '.join(where_parts)}"
        if group_by_parts:
            sql += f"\nGROUP BY {', '.join(group_by_parts)}"
        if order_parts:
            sql += f"\nORDER BY {', '.join(order_parts)}"
        if limit is not None:
            sql += f"\nLIMIT {limit}"

        return sql

    def _resolve_column_ref(
        self, ref: str, entity_map: dict[str, Any]
    ) -> str:
        """Resolve a dot-notation column reference to SQL.

        ``"transaction.fiscal_year"`` might resolve to a calculated field
        expression or to ``transaction.fiscal_year`` (plain column).
        """
        if "." not in ref:
            return ref

        entity_name, col_name = ref.split(".", 1)
        entity = entity_map.get(entity_name)
        if entity is None:
            return ref

        # Check if it's a calculated field
        cf = entity.get_calculated_field(col_name)
        if cf is not None:
            return cf.expression

        # Plain column with entity alias
        return f"{entity.sql_alias}.{col_name}"
