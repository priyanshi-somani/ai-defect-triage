"""Tests for Defect and DefectHistory domain models, constraints, and migrations.

Addresses Requirements:
- FR-004: Defect record fields, unique ID, created_at, reporter_id
- FR-005: Initial status 'Open', initial concurrency version 1
- NFR-004 / TC-SYS-003: Transaction atomicity and rollback on multi-table mutations
- NFR-005: Database foreign key constraints and schema integrity
- NFR-006 / FR-056 to FR-060: Optimistic concurrency control and stale data detection
- NFR-012: Version-controlled database schema migration upgrade and rollback
"""

import os
import tempfile
import pytest
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from alembic.config import Config
from alembic import command

from backend.models import (
    User,
    UserRole,
    Defect,
    DefectHistory,
    DefectStatus,
    DefectSeverity,
    DefectPriority,
    AuditActionType,
)


def test_defect_creation_and_defaults(db_session, make_user):
    """Verify defect creation, initial defaults, and relationship mappings (FR-004, FR-005)."""
    reporter = make_user(username="defect_reporter", role=UserRole.REPORTER)

    defect = Defect(
        id="DEF-1001",
        title="Login fails with unexpected 500 on special characters",
        description="Submitting login with unicode passwords results in an unhandled 500 error.",
        steps_to_reproduce="1. Navigate to /login.\n2. Enter password with emoji.\n3. Submit form.",
        expected_result="Authentication rejected with HTTP 400 or handled gracefully.",
        actual_result="Server crashed with HTTP 500 Internal Server Error.",
        environment="macOS 14.4 / Chrome 123.0 / Staging",
        module="Authentication",
        severity=DefectSeverity.MAJOR.value,
        priority=DefectPriority.P3.value,
        reporter_id=reporter.id,
    )
    db_session.add(defect)
    db_session.flush()

    assert defect.id == "DEF-1001"
    assert defect.status == DefectStatus.OPEN.value
    assert defect.version == 1
    assert defect.reopen_count == 0
    assert defect.assignee_id is None
    assert defect.created_at is not None
    assert defect.updated_at is not None
    assert defect.reporter.id == reporter.id
    assert defect.reporter.username == "defect_reporter"
    assert "DEF-1001" in repr(defect)


def test_foreign_key_enforcement_invalid_reporter(db_session):
    """Verify foreign key constraint rejects defect with non-existent reporter (NFR-005)."""
    defect = Defect(
        id="DEF-9999",
        title="Defect with invalid reporter reference",
        description="Testing foreign key constraint rejection on invalid reporter ID.",
        steps_to_reproduce="1. Step one.\n2. Step two.",
        expected_result="Database rejects invalid foreign key.",
        actual_result="Expected IntegrityError to be raised.",
        environment="Linux / Firefox / Dev",
        module="Core",
        reporter_id=99999,  # Non-existent user ID
    )
    db_session.add(defect)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_foreign_key_enforcement_invalid_assignee(db_session, make_user):
    """Verify foreign key constraint rejects defect with non-existent assignee (NFR-005)."""
    reporter = make_user(username="reporter_fk_test", role=UserRole.REPORTER)
    defect = Defect(
        id="DEF-9998",
        title="Defect with invalid assignee reference",
        description="Testing foreign key constraint rejection on invalid assignee ID.",
        steps_to_reproduce="1. Step one.\n2. Step two.",
        expected_result="Database rejects invalid foreign key.",
        actual_result="Expected IntegrityError to be raised.",
        environment="Windows / Edge / Dev",
        module="Core",
        reporter_id=reporter.id,
        assignee_id=99999,  # Non-existent assignee
    )
    db_session.add(defect)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_foreign_key_restrict_on_reporter_delete(db_session, make_user):
    """Verify RESTRICT delete rule prevents deletion of user with reported defects (NFR-005)."""
    reporter = make_user(username="cannot_delete_me", role=UserRole.REPORTER)
    defect = Defect(
        id="DEF-1002",
        title="Defect linking to user to test RESTRICT delete",
        description="Ensures data integrity: reporter record cannot be silently dropped.",
        steps_to_reproduce="1. Step one.\n2. Step two.",
        expected_result="Integrity error preventing reporter deletion.",
        actual_result="Expected IntegrityError on reporter delete.",
        environment="Linux / Chrome / Dev",
        module="Core",
        reporter_id=reporter.id,
    )
    db_session.add(defect)
    db_session.flush()

    db_session.delete(reporter)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_defect_history_relationship_and_metadata(db_session, make_user):
    """Verify DefectHistory entity properties, relationship linkage, and audit logging."""
    reporter = make_user(username="audit_tester", role=UserRole.REPORTER)
    defect = Defect(
        id="DEF-1003",
        title="Audit history verification defect",
        description="Verifies that audit history entries link correctly to defect and actor.",
        steps_to_reproduce="1. Step one.\n2. Step two.",
        expected_result="History entry recorded and readable via relationship.",
        actual_result="History entry mapped correctly.",
        environment="macOS / Safari / Dev",
        module="Audit",
        reporter_id=reporter.id,
    )
    db_session.add(defect)
    db_session.flush()

    history = DefectHistory(
        defect_id=defect.id,
        changed_by_user_id=reporter.id,
        action_type=AuditActionType.CREATED.value,
        field_name=None,
        old_value=None,
        new_value=DefectStatus.OPEN.value,
        version_snapshot=1,
    )
    db_session.add(history)
    db_session.flush()

    assert len(defect.history_entries) == 1
    assert defect.history_entries[0].action_type == AuditActionType.CREATED.value
    assert defect.history_entries[0].changed_by.username == "audit_tester"
    assert defect.history_entries[0].defect.id == "DEF-1003"
    assert "DEF-1003" in repr(history)


def test_tc_sys_003_transaction_atomicity_and_rollback(db_session, make_user):
    """Verify transaction atomicity: multi-table mutation rolls back fully on failure (NFR-004, TC-SYS-003)."""
    reporter = make_user(username="atomic_user", role=UserRole.REPORTER)

    # Attempt a multi-entity operation where the second step fails due to FK violation
    defect = Defect(
        id="DEF-1004",
        title="Atomic transaction test defect",
        description="Tests that failure during multi-table mutation rolls back the entire transaction.",
        steps_to_reproduce="1. Step one.\n2. Step two.",
        expected_result="Zero records persisted if any step fails.",
        actual_result="Transaction rolls back cleanly.",
        environment="Linux / Firefox / Test",
        module="System",
        reporter_id=reporter.id,
    )
    db_session.add(defect)

    # Invalid history record with non-existent user ID
    invalid_history = DefectHistory(
        defect_id=defect.id,
        changed_by_user_id=99999,  # Violates foreign key
        action_type=AuditActionType.CREATED.value,
        version_snapshot=1,
    )
    db_session.add(invalid_history)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()

    # Verify atomicity: DEF-1004 was NOT committed (zero orphaned rows)
    persisted_defect = db_session.execute(
        select(Defect).where(Defect.id == "DEF-1004")
    ).scalar_one_or_none()
    assert persisted_defect is None


def test_optimistic_concurrency_version_increment(db_session, make_user):
    """Verify that updates to Defect automatically increment the optimistic lock version token."""
    reporter = make_user(username="lock_tester", role=UserRole.REPORTER)
    defect = Defect(
        id="DEF-1005",
        title="Optimistic concurrency version increment test",
        description="Verify SQLAlchemy automatic version increment upon mutation.",
        steps_to_reproduce="1. Step one.\n2. Step two.",
        expected_result="Version increments from 1 to 2, then to 3.",
        actual_result="Version token incremented accurately.",
        environment="Windows / Chrome / Dev",
        module="Core",
        reporter_id=reporter.id,
    )
    db_session.add(defect)
    db_session.flush()
    assert defect.version == 1

    defect.title = "Updated Title - Increment Version"
    db_session.flush()
    assert defect.version == 2

    defect.status = DefectStatus.TRIAGED.value
    db_session.flush()
    assert defect.version == 3


def test_optimistic_concurrency_stale_update_detection(make_user):
    """Verify detection of stale concurrent update and rejection via StaleDataError (NFR-006, FR-056 to FR-060)."""
    # Create a dedicated SQLite in-memory engine for concurrent session simulation
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    from backend.database import Base
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)

    # Setup reporter and initial defect
    with Session() as s0:
        user = User(
            username="concurrent_user",
            email="concurrent@example.com",
            password_hash="hashedpass",
            role=UserRole.DEVELOPER.value,
        )
        s0.add(user)
        s0.flush()

        defect = Defect(
            id="DEF-CONC-01",
            title="Initial Title for Concurrency Test",
            description="Testing detection of concurrent stale updates without overwrites.",
            steps_to_reproduce="1. Step one.\n2. Step two.",
            expected_result="StaleDataError raised on conflict.",
            actual_result="Second committer rejected.",
            environment="macOS / Chrome / Dev",
            module="Concurrency",
            reporter_id=user.id,
        )
        s0.add(defect)
        s0.commit()

    # Simulate two independent concurrent sessions
    session_a = Session()
    session_b = Session()

    try:
        # Both sessions load the same defect at version 1
        defect_a = session_a.get(Defect, "DEF-CONC-01")
        defect_b = session_b.get(Defect, "DEF-CONC-01")

        assert defect_a.version == 1
        assert defect_b.version == 1

        # Session A modifies and commits first -> version becomes 2 in database
        defect_a.title = "Title updated by Session A"
        session_a.commit()
        assert defect_a.version == 2

        # Session B attempts to modify based on stale version 1 -> StaleDataError expected
        defect_b.title = "Title updated by Session B (Conflicting)"
        with pytest.raises(StaleDataError):
            session_b.commit()

        session_b.rollback()

        # Confirm database holds Session A's update and version is 2
        with Session() as s_check:
            fresh_defect = s_check.get(Defect, "DEF-CONC-01")
            assert fresh_defect.title == "Title updated by Session A"
            assert fresh_defect.version == 2
    finally:
        session_a.close()
        session_b.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_nfr_012_alembic_migration_execution_and_rollback():
    """Verify that Alembic migrations run cleanly forward and backward against a fresh database (NFR-012)."""
    # Create temporary directory and database file for migration testing
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = os.path.join(tmp_dir, "migration_test.db").replace("\\", "/")
        test_db_url = f"sqlite:///{test_db_path}"

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)

        # 1. Upgrade from empty database to head
        command.upgrade(alembic_cfg, "head")

        # Verify tables exist after upgrade
        engine = create_engine(test_db_url)
        with engine.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            table_names = inspector.get_table_names()
            assert "users" in table_names
            assert "defects" in table_names
            assert "defect_history" in table_names
            assert "alembic_version" in table_names

        # 2. Downgrade from head back to base
        command.downgrade(alembic_cfg, "base")

        # Verify application tables were dropped after downgrade
        with engine.connect() as conn:
            inspector = inspect(conn)
            table_names_after = inspector.get_table_names()
            assert "defects" not in table_names_after
            assert "defect_history" not in table_names_after
            assert "users" not in table_names_after

        engine.dispose()
