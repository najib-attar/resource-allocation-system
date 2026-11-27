"""Protect the decision history of resolved group meeting replacements."""

from alembic import op


revision = "0051i"
down_revision = "0051h"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION protect_group_meeting_reschedule_decisions() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        parent_id bigint;
        proposal_status varchar(20);
    BEGIN
        IF TG_OP = 'TRUNCATE' THEN
            RAISE EXCEPTION 'Reschedule decision history cannot be truncated' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (OLD.proposal_id, OLD.user_id) IS DISTINCT FROM (NEW.proposal_id, NEW.user_id) THEN
            RAISE EXCEPTION 'Reschedule voter identity is immutable' USING ERRCODE = '23514';
        END IF;
        parent_id := CASE WHEN TG_OP = 'INSERT' THEN NEW.proposal_id ELSE OLD.proposal_id END;
        SELECT status INTO proposal_status FROM group_meeting_reschedule WHERE id = parent_id FOR UPDATE;
        IF proposal_status IS DISTINCT FROM 'Pending Approval' THEN
            RAISE EXCEPTION 'Resolved reschedule decisions are immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
    $$;
    CREATE TRIGGER protect_group_reschedule_decision_history BEFORE INSERT OR UPDATE OR DELETE
    ON group_meeting_reschedule_decision FOR EACH ROW EXECUTE FUNCTION protect_group_meeting_reschedule_decisions();
    CREATE TRIGGER protect_group_reschedule_decision_truncate BEFORE TRUNCATE ON group_meeting_reschedule_decision
    FOR EACH STATEMENT EXECUTE FUNCTION protect_group_meeting_reschedule_decisions();
    """)


def downgrade():
    op.execute("DROP TRIGGER protect_group_reschedule_decision_truncate ON group_meeting_reschedule_decision")
    op.execute("DROP TRIGGER protect_group_reschedule_decision_history ON group_meeting_reschedule_decision")
    op.execute("DROP FUNCTION protect_group_meeting_reschedule_decisions()")
