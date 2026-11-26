"""Scope group meeting room requests to the existing one-time approval aggregate."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0051h"
down_revision = "0051g"
branch_labels = None
depends_on = None

GROUP_FK_INDEXES = (
    ("group_meeting_consent", "user_id"),
    ("group_meeting_event", "actor_id"),
    ("group_meeting_reschedule", "original_room_request_id"),
    ("group_meeting_reschedule", "room_request_id"),
    ("group_meeting_reschedule_decision", "user_id"),
)

STUDENT_ROLE = ("NOT EXISTS (SELECT 1 FROM university_user u JOIN role p ON p.id=u.primary_role_id "
                "WHERE u.id=r.organizer_id AND p.name='Student')")
GROUP_OR_STUDENT = (f"(r.group_participant_ids IS NULL AND {STUDENT_ROLE})"
                    " OR (r.group_participant_ids IS NOT NULL AND EXISTS "
                    "(SELECT 1 FROM room_invitation WHERE request_id=k))")


def _replace_guard(function, old, new):
    definition = op.get_bind().scalar(sa.text("SELECT pg_get_functiondef(CAST(:function AS regprocedure))"),
                                      {"function": function})
    if definition.count(old) != 1:
        raise RuntimeError(f"Unexpected definition of {function}; review the room migration.")
    op.execute(definition.replace(old, new))


SERIES_LOOKUP = "SELECT id INTO s FROM reservation_series WHERE room_request_id=k;"
SERIES_GUARD = """IF FOUND AND EXISTS (SELECT 1 FROM student_room_request WHERE id=k AND group_participant_ids IS NOT NULL) THEN
     RAISE EXCEPTION 'A group meeting room request must be one-time' USING ERRCODE='23514';
 END IF;"""

GROUP_CONFIRMATION = "IF meeting.status <> 'Confirmed' THEN"
GROUP_CONFIRMATION_GUARD = """IF meeting.status IN ('Pending Approval', 'Confirmed') AND EXISTS (
        SELECT FROM student_room_request r WHERE r.id=meeting.room_request_id AND r.group_participant_ids IS NOT NULL
        AND (r.organizer_id<>meeting.organizer_id OR r.start_at<>meeting.start_at OR r.end_at<>meeting.end_at
            OR r.status<>'Confirmed' OR NOT r.required_features @> meeting.required_features
            OR r.group_participant_ids IS DISTINCT FROM (SELECT jsonb_agg(p.user_id ORDER BY p.user_id)
                FROM group_meeting_participant p WHERE p.meeting_id=key))) THEN
        RAISE EXCEPTION 'Group meeting must match its approved room scope' USING ERRCODE='23514';
    END IF;
        """

CONFIRMED_ROOM = "m.status = 'Confirmed'"
ACTIVE_SCOPED_ROOM = ("(m.status = 'Confirmed' OR (m.status = 'Pending Approval' AND EXISTS "
                     "(SELECT FROM student_room_request r WHERE r.id=OLD.request_id AND r.group_participant_ids IS NOT NULL)))")


def upgrade():
    for table, column in GROUP_FK_INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column])
    op.add_column("student_room_request", sa.Column("group_participant_ids", postgresql.JSONB()))
    op.add_column("student_room_request", sa.Column("group_submission_key", sa.String(64)))
    op.create_unique_constraint("uq_student_room_group_submission_key", "student_room_request", ["group_submission_key"])
    _replace_guard("ras_room_single_shape(bigint)", STUDENT_ROLE, GROUP_OR_STUDENT)
    _replace_guard("ras_room_shape(bigint)", SERIES_LOOKUP, f"{SERIES_LOOKUP}\n {SERIES_GUARD}")
    _replace_guard("enforce_group_meeting()", GROUP_CONFIRMATION, GROUP_CONFIRMATION_GUARD + GROUP_CONFIRMATION)
    _replace_guard("protect_group_meeting_room()", CONFIRMED_ROOM, ACTIVE_SCOPED_ROOM)
    op.execute("""
    CREATE FUNCTION ras_group_meeting_room_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='UPDATE' THEN
            IF OLD.group_participant_ids IS DISTINCT FROM NEW.group_participant_ids
                OR OLD.group_submission_key IS DISTINCT FROM NEW.group_submission_key
                OR (OLD.group_participant_ids IS NOT NULL AND (
                    OLD.organizer_id IS DISTINCT FROM NEW.organizer_id
                    OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
                    OR OLD.faculty_id IS DISTINCT FROM NEW.faculty_id OR OLD.approver_id IS DISTINCT FROM NEW.approver_id
                    OR OLD.start_at IS DISTINCT FROM NEW.start_at OR OLD.end_at IS DISTINCT FROM NEW.end_at
                    OR OLD.required_features IS DISTINCT FROM NEW.required_features
                    OR OLD.revision IS DISTINCT FROM NEW.revision)) THEN
                RAISE EXCEPTION 'Group room authorization and its approved scope cannot be revised' USING ERRCODE='23514';
            END IF;
        END IF;
        IF NEW.group_participant_ids IS NULL AND NEW.group_submission_key IS NULL THEN RETURN NEW; END IF;
        IF NEW.group_submission_key IS NULL OR NEW.group_submission_key !~ '^[0-9a-f]{64}$'
            OR jsonb_typeof(NEW.group_participant_ids) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'A group room request needs scoped participants and an idempotency key' USING ERRCODE='23514';
        END IF;
        IF NEW.category <> 'meeting' OR NEW.approver_id=NEW.organizer_id OR NEW.revision<>1
            OR NEW.duration_minutes NOT BETWEEN 15 AND 120 OR NEW.duration_minutes % 15<>0
            OR NEW.attendee_count NOT BETWEEN 2 AND 8
            OR jsonb_array_length(NEW.group_participant_ids)<>NEW.attendee_count
            OR NOT NEW.group_participant_ids @> jsonb_build_array(NEW.organizer_id) THEN
            RAISE EXCEPTION 'A group room request needs a distinct approver and exact meeting scope' USING ERRCODE='23514';
        END IF;
        IF TG_OP='INSERT' THEN
            IF NEW.status <> 'Pending Faculty Approval' OR NEW.approved_by IS NOT NULL OR NEW.approved_revision IS NOT NULL
                OR NEW.attendee_count <> (SELECT count(*) FROM university_user u
                    JOIN role p ON p.id=u.primary_role_id JOIN login_account a ON a.user_id=u.id
                    WHERE NEW.group_participant_ids @> jsonb_build_array(u.id) AND a.enabled AND lower(u.status)='active'
                    AND (p.name IN ('Student','Instructor','Staff','Administrator') OR (p.name='TeachingAssistant' AND
                        regexp_replace(lower(btrim(u.assistant_type)), '[[:space:]]+', ' ', 'g') IN ('research assistant','research and teaching')))) THEN
                RAISE EXCEPTION 'Group room scope requires distinct active pilot participants and faculty review' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER group_meeting_room_scope BEFORE INSERT OR UPDATE ON student_room_request
    FOR EACH ROW EXECUTE FUNCTION ras_group_meeting_room_scope();
    """)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM student_room_request WHERE group_participant_ids IS NOT NULL)")):
        raise RuntimeError("Downgrade would discard group room authorization history. Preserve and reconcile those requests first.")
    op.execute("DROP TRIGGER group_meeting_room_scope ON student_room_request; DROP FUNCTION ras_group_meeting_room_scope()")
    _replace_guard("protect_group_meeting_room()", ACTIVE_SCOPED_ROOM, CONFIRMED_ROOM)
    _replace_guard("enforce_group_meeting()", GROUP_CONFIRMATION_GUARD + GROUP_CONFIRMATION, GROUP_CONFIRMATION)
    _replace_guard("ras_room_shape(bigint)", f"{SERIES_LOOKUP}\n {SERIES_GUARD}", SERIES_LOOKUP)
    _replace_guard("ras_room_single_shape(bigint)", GROUP_OR_STUDENT, STUDENT_ROLE)
    op.drop_constraint("uq_student_room_group_submission_key", "student_room_request", type_="unique")
    op.drop_column("student_room_request", "group_submission_key")
    op.drop_column("student_room_request", "group_participant_ids")
    for table, column in reversed(GROUP_FK_INDEXES):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
