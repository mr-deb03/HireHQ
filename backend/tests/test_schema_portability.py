"""The schema must be creatable on PostgreSQL, not just on SQLite.

The test suite runs on SQLite, which does not verify that a foreign key's target table
exists when the table is created. PostgreSQL does. A pair of tables that reference each
other therefore passes every test here and then fails to build at all in production:

    asyncpg.exceptions.UndefinedTableError: relation "users" does not exist

That is precisely what happened. Three pairs of tables referenced each other, SQLAlchemy
could not order them ("unresolvable cycles between tables ..."), and it fell back to
alphabetical order - so ``applications`` was created before ``users``, which it depends
on. Every test passed. The production database could not be built.

The fix for a cycle is ``use_alter=True`` on one side, which defers that constraint to an
ALTER TABLE after both tables exist. These tests fail if a new circular reference is added
without one, and if the deferred constraints stop being created.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from sqlalchemy.schema import CreateTable, ForeignKeyConstraint

import app.models  # noqa: F401  - registers every model on the metadata
from app.db.base import Base

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


class TestTableOrdering:
    def test_tables_sort_without_unresolvable_cycles(self):
        """SQLAlchemy must be able to order every table by its dependencies.

        When it cannot it does not raise - it warns and returns an arbitrary order, which
        is why this failure reaches production instead of the test suite.
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Accessing the property is what performs the sort and emits the warning.
            ordered = Base.metadata.sorted_tables

        assert len(ordered) == len(Base.metadata.tables)
        cycles = [w for w in caught if "cycle" in str(w.message).lower()]
        assert not cycles, (
            "The schema contains circular foreign keys that SQLAlchemy cannot order, so "
            "CREATE TABLE will run in an arbitrary order and fail on PostgreSQL. Mark one "
            "side of each cycle with use_alter=True.\n"
            + "\n".join(f"  {w.message}" for w in cycles)
        )

    def test_every_table_is_created_after_what_it_references(self):
        """The ordering itself, checked directly rather than trusting the absence of a
        warning. A constraint marked use_alter is exempt: it is added afterwards."""
        position = {t.name: i for i, t in enumerate(Base.metadata.sorted_tables)}
        violations = []

        for table in Base.metadata.sorted_tables:
            for constraint in table.constraints:
                if not isinstance(constraint, ForeignKeyConstraint):
                    continue
                if constraint.use_alter:
                    continue
                for fk in constraint.elements:
                    target = fk.column.table.name
                    if target == table.name:
                        continue  # self-reference is fine
                    if position[target] > position[table.name]:
                        violations.append(f"{table.name} -> {target}")

        assert not violations, (
            "These tables are created before a table they reference, which PostgreSQL "
            "rejects with 'relation does not exist':\n"
            + "\n".join(f"  {v}" for v in sorted(set(violations)))
        )


class TestDeferredConstraintsAreActuallyCreated:
    """``use_alter`` fixes the ordering but introduces a second trap.

    Alembic's ``create_table`` skips a constraint marked ``use_alter`` and does *not* emit
    the ALTER itself, so the foreign key silently never exists - no error, no failed
    migration, just a column with no referential integrity and no ON DELETE behaviour. The
    migration has to add it explicitly.
    """

    def test_use_alter_constraints_exist_in_the_models(self):
        deferred = {
            c.name
            for t in Base.metadata.tables.values()
            for c in t.constraints
            if isinstance(c, ForeignKeyConstraint) and c.use_alter
        }
        assert deferred, (
            "Expected the known circular foreign keys to be marked use_alter. If a cycle "
            "was genuinely removed from the schema, update this test."
        )

    def test_migration_explicitly_creates_every_deferred_constraint(self):
        """The regression guard: each deferred FK needs its own create_foreign_key."""
        migrations = "\n".join(
            p.read_text(encoding="utf-8") for p in MIGRATIONS_DIR.glob("*.py")
        )
        assert migrations, f"no migration files found in {MIGRATIONS_DIR}"

        missing = []
        for table in Base.metadata.tables.values():
            for constraint in table.constraints:
                if not isinstance(constraint, ForeignKeyConstraint):
                    continue
                if not constraint.use_alter:
                    continue
                name = constraint.name
                # Either an explicit op.create_foreign_key naming it, or an
                # op.f('<name>') passed to one.
                if not re.search(rf"create_foreign_key\([^)]*{re.escape(str(name))}", migrations, re.S):
                    missing.append(f"{table.name}.{name}")

        assert not missing, (
            "These foreign keys are marked use_alter, so create_table skips them and "
            "Alembic does not add them either. The migration must call "
            "op.create_foreign_key() for each, or the constraint will not exist in the "
            "database at all:\n" + "\n".join(f"  {m}" for m in sorted(missing))
        )


class TestPostgresDDL:
    def test_create_table_ddl_compiles_for_postgresql(self):
        """Compile every CREATE TABLE against the PostgreSQL dialect.

        The portable column types (GUID, JSONType, UTCDateTime, StringArray) resolve to
        different native types per backend; this catches one that cannot render for
        PostgreSQL without needing a live server.
        """
        from sqlalchemy.dialects import postgresql

        dialect = postgresql.dialect()
        for table in Base.metadata.sorted_tables:
            ddl = str(CreateTable(table).compile(dialect=dialect))
            assert ddl.strip().upper().startswith("CREATE TABLE"), table.name
