"""Validate ordering and support reverse foreign-key lookups without changing data."""

from alembic import op

revision = "0041b"
down_revision = "0041a"
branch_labels = None
depends_on = None

CHECKS = (
    ("university_user", "ck_user_source_order", "source_order > 0"),
    ("resource", "ck_resource_source_order", "source_order > 0"),
    ("resource_request", "ck_request_submission_order", "submission_order > 0"),
    ("busy_slot", "ck_busy_source_order", "source_order > 0"),
    ("user_role", "ck_user_role_ordinal", "ordinal > 0"),
    ("request_slot", "ck_request_slot_ordinal", "ordinal > 0"),
    ("request_participant", "ck_request_participant_ordinal", "ordinal > 0"),
    ("allocation_run", "ck_run_input_revision", "input_revision >= 0"),
    ("request_decision", "ck_decision_ordinal", "ordinal > 0"),
    ("allocation", "ck_allocation_engine_id", "engine_id >= 0"),
    # Revision 0041a used zero for unknown historical participant ordering.
    ("allocation_participant", "ck_allocation_participant_ordinal", "ordinal >= 0"),
    ("suggestion_group", "ck_suggestion_group_ordinal", "ordinal > 0"),
    ("meeting_suggestion", "ck_suggestion_scores", "rank > 0 AND score >= 0 AND time_distance >= 0 AND day_distance >= 0 AND conflict_count >= 0"),
)
INDEXES = (
    ("user_role", "ix_user_role_role_id", ["role_id"]),
    ("request_participant", "ix_request_participant_user_id", ["user_id"]),
    ("request_decision", "ix_request_decision_request_id", ["request_id"]),
    ("allocation", "ix_allocation_decision", ["run_id", "request_id"]),
    ("allocation_participant", "ix_allocation_participant_user_id", ["user_id"]),
    ("meeting_suggestion", "ix_meeting_suggestion_resource_id", ["resource_id"]),
)


def upgrade():
    # Invalid preexisting records fail the transactional upgrade; never delete them.
    for table, name, condition in CHECKS:
        op.create_check_constraint(name, table, condition)
    op.create_unique_constraint("uq_decision_order", "request_decision", ["run_id", "ordinal"])
    op.create_unique_constraint("uq_suggestion_group_order", "suggestion_group", ["run_id", "ordinal"])
    for table, name, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade():
    for table, name, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_constraint("uq_suggestion_group_order", "suggestion_group", type_="unique")
    op.drop_constraint("uq_decision_order", "request_decision", type_="unique")
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
