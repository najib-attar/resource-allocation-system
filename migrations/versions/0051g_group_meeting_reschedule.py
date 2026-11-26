"""Record independently approved replacements of confirmed group meetings."""

import sqlalchemy as sa
from alembic import op


revision = "0051g"
down_revision = "0051f"
branch_labels = None
depends_on = None


ORIGINAL_CONSENT_RULE = "c.revision <> meeting.revision"
HISTORICAL_CONSENT_RULE = """c.revision <> COALESCE(
                            (SELECT min(source_revision) FROM group_meeting_reschedule
                             WHERE meeting_id = key AND status = 'Applied'), meeting.revision)"""


def _replace_consent_rule(previous, replacement):
    # Keep the installed 0051f trigger and every other sub-check intact.
    op.execute(f"""
    DO $migration$
    DECLARE
        definition text := pg_get_functiondef('enforce_group_meeting()'::regprocedure);
        previous text := $rule${previous}$rule$;
        replacement text := $rule${replacement}$rule$;
    BEGIN
        IF (length(definition) - length(replace(definition, previous, ''))) <> length(previous) THEN
            RAISE EXCEPTION 'Unexpected relocation approval constraint definition';
        END IF;
        EXECUTE replace(definition, previous, replacement);
    END;
    $migration$;
    """)


def upgrade():
    op.create_table(
        "group_meeting_reschedule",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("meeting_id", sa.BigInteger(), sa.ForeignKey("group_meeting.id"), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("original_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_room_request_id", sa.BigInteger(), sa.ForeignKey("student_room_request.id")),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("room_request_id", sa.BigInteger(), sa.ForeignKey("student_room_request.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("submission_key", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('Pending Approval', 'Applied', 'Declined', 'Withdrawn', 'Superseded')"),
        sa.CheckConstraint("source_revision > 0 AND original_start_at < original_end_at AND "
                           "start_at <> original_start_at AND end_at - start_at = original_end_at - original_start_at"),
        sa.CheckConstraint("(original_room_request_id IS NULL) = (room_request_id IS NULL)"),
        sa.CheckConstraint("(status = 'Pending Approval') = (resolved_at IS NULL)"),
    )
    op.create_index("ix_group_meeting_reschedule_meeting_id", "group_meeting_reschedule", ["meeting_id"])
    op.create_index("uq_group_reschedule_pending", "group_meeting_reschedule", ["meeting_id"], unique=True,
                    postgresql_where=sa.text("status = 'Pending Approval'"))
    op.create_index("uq_group_reschedule_applied", "group_meeting_reschedule", ["meeting_id", "source_revision"],
                    unique=True, postgresql_where=sa.text("status = 'Applied'"))
    op.create_table(
        "group_meeting_reschedule_decision",
        sa.Column("proposal_id", sa.BigInteger(), sa.ForeignKey("group_meeting_reschedule.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("university_user.id"), primary_key=True),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("decision IN ('Pending', 'Approved', 'Declined')"),
        sa.CheckConstraint("(decision = 'Pending') = (decided_at IS NULL)"),
    )
    op.execute("""
    CREATE FUNCTION enforce_group_meeting_reschedule() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        item group_meeting_reschedule%ROWTYPE;
        meeting group_meeting%ROWTYPE;
    BEGIN
        IF TG_TABLE_NAME = 'group_meeting_reschedule' THEN
            SELECT * INTO item FROM group_meeting_reschedule WHERE id = NEW.id;
        ELSE
            IF TG_OP = 'UPDATE' AND (OLD.proposal_id, OLD.user_id) <> (NEW.proposal_id, NEW.user_id) THEN
                RAISE EXCEPTION 'Reschedule voter identity is immutable' USING ERRCODE = '23514';
            END IF;
            SELECT * INTO item FROM group_meeting_reschedule
            WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.proposal_id ELSE NEW.proposal_id END;
        END IF;
        IF NOT FOUND THEN
            RETURN NULL;
        END IF;
        SELECT * INTO meeting FROM group_meeting WHERE id = item.meeting_id;
        IF NOT EXISTS (SELECT FROM group_meeting_reschedule_decision d WHERE d.proposal_id = item.id
                       AND d.user_id = meeting.organizer_id AND d.decision = 'Approved')
            OR EXISTS (SELECT FROM group_meeting_reschedule_decision d WHERE d.proposal_id = item.id
                       AND NOT EXISTS (SELECT FROM group_meeting_participant p WHERE p.meeting_id = item.meeting_id
                                       AND p.user_id = d.user_id AND p.side <> 'optional'))
            OR EXISTS (SELECT FROM group_meeting_participant p WHERE p.meeting_id = item.meeting_id
                       AND p.side <> 'optional' AND NOT EXISTS (SELECT FROM group_meeting_reschedule_decision d
                         WHERE d.proposal_id = item.id AND d.user_id = p.user_id)) THEN
            RAISE EXCEPTION 'Reschedule requires the organizer and every required participant' USING ERRCODE = '23514';
        END IF;
        IF item.status = 'Applied' AND (meeting.revision <= item.source_revision
            OR (meeting.revision = item.source_revision + 1
                AND (meeting.start_at, meeting.end_at, meeting.room_request_id) IS DISTINCT FROM
                    (item.start_at, item.end_at, item.room_request_id))
            OR EXISTS (SELECT FROM group_meeting_reschedule_decision d WHERE d.proposal_id = item.id
                       AND d.decision <> 'Approved')) THEN
            RAISE EXCEPTION 'Applied replacements require unanimous approvals and a matching revision'
            USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """)
    op.execute("""
    CREATE CONSTRAINT TRIGGER check_group_reschedule AFTER INSERT OR UPDATE ON group_meeting_reschedule
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_group_meeting_reschedule()
    """)
    op.execute("""
    CREATE CONSTRAINT TRIGGER check_group_reschedule_decision AFTER INSERT OR UPDATE OR DELETE
    ON group_meeting_reschedule_decision DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION enforce_group_meeting_reschedule()
    """)
    op.execute("""
    CREATE FUNCTION protect_group_meeting_reschedule_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Reschedule audit history cannot be deleted' USING ERRCODE = '23514';
        END IF;
        IF OLD.status <> 'Pending Approval'
            OR (OLD.id, OLD.meeting_id, OLD.source_revision, OLD.created_at, OLD.submission_key,
                OLD.original_start_at, OLD.original_end_at, OLD.original_room_request_id,
                OLD.start_at, OLD.end_at, OLD.room_request_id) IS DISTINCT FROM
               (NEW.id, NEW.meeting_id, NEW.source_revision, NEW.created_at, NEW.submission_key,
                NEW.original_start_at, NEW.original_end_at, NEW.original_room_request_id,
                NEW.start_at, NEW.end_at, NEW.room_request_id) THEN
            RAISE EXCEPTION 'Reschedule arrangement and resolved history are immutable' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $$;
    CREATE TRIGGER protect_group_reschedule_history BEFORE UPDATE OR DELETE ON group_meeting_reschedule
    FOR EACH ROW EXECUTE FUNCTION protect_group_meeting_reschedule_history();
    """)
    _replace_consent_rule(ORIGINAL_CONSENT_RULE, HISTORICAL_CONSENT_RULE)


def downgrade():
    op.execute("LOCK TABLE group_meeting_reschedule IN ACCESS EXCLUSIVE MODE")
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT FROM group_meeting_reschedule) THEN
            RAISE EXCEPTION 'Back up and explicitly resolve reschedule history before downgrade';
        END IF;
    END $$
    """)
    _replace_consent_rule(HISTORICAL_CONSENT_RULE, ORIGINAL_CONSENT_RULE)
    op.drop_table("group_meeting_reschedule_decision")
    op.drop_table("group_meeting_reschedule")
    op.execute("DROP FUNCTION protect_group_meeting_reschedule_history()")
    op.execute("DROP FUNCTION enforce_group_meeting_reschedule()")
