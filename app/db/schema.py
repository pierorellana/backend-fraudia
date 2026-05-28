from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.engine import Engine

CODED_TABLES = (
    ("asegurados", "id_asegurado", "ASE"),
    ("polizas", "id_poliza", "POL"),
    ("proveedores", "id_proveedor", "PRO"),
    ("siniestros", "id_siniestro", "SIN"),
)


def ensure_code_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        quote = connection.dialect.identifier_preparer.quote
        for table_name, primary_key, prefix in CODED_TABLES:
            if table_name not in table_names:
                continue

            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "code" not in columns:
                connection.execute(text(f"ALTER TABLE {quote(table_name)} ADD COLUMN {quote('code')} VARCHAR(20)"))

            _backfill_missing_codes(connection, table_name, primary_key, prefix, quote)
            if not _has_unique_code_constraint(inspector, table_name):
                index_name = f"uq_{table_name}_code"
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {quote(index_name)} "
                        f"ON {quote(table_name)} ({quote('code')})"
                    )
                )


def _has_unique_code_constraint(inspector, table_name: str) -> bool:
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and index.get("column_names") == ["code"]:
            return True

    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == ["code"]:
            return True

    return False


def _backfill_missing_codes(connection, table_name: str, primary_key: str, prefix: str, quote) -> None:
    rows = connection.execute(
        text(
            f"SELECT {quote(primary_key)} AS id, {quote('code')} AS code "
            f"FROM {quote(table_name)} ORDER BY {quote(primary_key)}"
        )
    ).mappings()
    rows = list(rows)
    used_codes = {str(row["code"]).strip() for row in rows if row["code"] and str(row["code"]).strip()}
    next_number = 1

    for row in rows:
        if row["code"] and str(row["code"]).strip():
            continue

        while True:
            candidate = f"{prefix}-{next_number:04d}"
            next_number += 1
            if candidate not in used_codes:
                used_codes.add(candidate)
                break

        connection.execute(
            text(
                f"UPDATE {quote(table_name)} SET {quote('code')} = :code "
                f"WHERE {quote(primary_key)} = :record_id"
            ),
            {"code": candidate, "record_id": row["id"]},
        )
