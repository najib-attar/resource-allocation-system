"""Generate reviewable Mermaid ER sources and a physical catalog from ORM metadata."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from web.persistence.models import Base


PURPOSES = {
    'request_eligibility': 'Explicit administrative eligibility for the current request revision; legacy provenance is unverified, never automatically approved.',
    'eligibility_event': 'Append-only eligibility decision/revision audit, separate from allocation outcomes and calendar publication.',
    'allocation_eligibility': 'Immutable per-run request revision and eligibility-version proof used to reject stale replacement publications.',
    'scheduling_cost_policy_revision': 'Immutable institutional numerical intent and canonical digest; not approval, activation or calibrated defaults.',
    'scheduling_cost_policy_event': 'Immutable governance decision associations and explicit approval/activation/deactivation provenance; no management commands.',
    'scheduling_cost_policy_head': 'Optional singleton optimistic concurrency and active-event pointer; empty until future authorized governance initializes it.',
    'scheduling_cost_policy_authority_revision': 'Immutable explicit named-capability grant/revocation history; no default authority for any existing role.',
    'scheduling_preference_revision': 'Private self-owned append-only configured/deactivated personal intent; no availability, numerical policy or optimizer activation.',
    'reservation_priority_override': 'Immutable shared room/equipment priority override with responsible actor, server time, original/selected priority and mandatory reason.',
    'reservation_series': 'Shared immutable bounded weekly proposal linked to one existing room or borrowing request; no duplicated requirements or approval system.',
    'reservation_occurrence': 'Ordered real dated series interval, cancellation/completion state and exact links to existing reservations and physical loans.',
    'resource_feedback': 'Private optional room/equipment usage report, immutable reporter/booking association, current review state and retry identity.',
    'feedback_event': 'Private actor/time/status history, staff responses and idempotent actions; existing notification receipts are reused.',
    "waiting_list_entry": "Shared consent, responsible-staff preapproval, contextual FCFS identity and notification milestones; requirements and reservations remain in the original room/borrowing records.",
    "role": "Primary engine roles and preserved assigned-role labels; not authentication permissions.",
    "organization_unit": "Named university units with optional known type and parent.",
    "university_user": "University identity and profile; primary role and optional primary unit.",
    "user_role": "Ordered many-to-many assigned role labels.",
    "resource": "Typed classrooms, laboratories and meeting rooms with facilities and capacity.",
    "resource_request": "Ordered request identity, requirements and private-by-default academic publication; optional explicit instructor label.",
    "request_slot": "Ordered weekly occurrences; multiple rows represent recurrence.",
    "exam_details": "Optional one-to-one examination metadata.",
    "request_participant": "Ordered required committee participants and descriptive roles.",
    "busy_slot": "Explicit weekly user commitments, independent of allocation runs.",
    "allocation_run": "Immutable input/build provenance and execution status for one engine batch.",
    "application_state": "Singleton strategy, input revision and currently published run.",
    "request_decision": "One decision per run/request, including immutable engine detail/history.",
    "allocation": "Assigned resource/time/count, linked to exactly one run/request decision.",
    "allocation_participant": "Ordered required human commitments of an allocation.",
    "suggestion_group": "Decision-specific suggestion scan, including a scan yielding no alternatives.",
    "meeting_suggestion": "Ranked structured time/resource alternatives returned by C++.",
    "request_history": "Timestamped save/import/decision events with optional run provenance.",
    "login_account": "Trusted login identity, password hash, administration grant, revocation and throttling.",
    "logged_out_session": "Durable per-login denial keyed by account generation and SHA-256 nonce digest; prevents signed-cookie replay after logout without ending other logins.",
    "research_task": "Private owner-scoped research planning tasks with due dates and revisions.",
    "academic_period": "Explicit named calendar validity and timezone; no inferred legacy dates.",
    "course_import": "Source and supplement digests, provenance and validation report for one imported academic period.",
    "course": "Shared catalogue identity with one course code and canonical title.",
    "course_section": "One published CRN per academic period with exact section title, source metadata and optional quota.",
    "teaching_assignment": "Ordered public instructor attribution with an optional existing university identity.",
    "course_session": "Ordered published weekly meeting with half-open interval boundaries and an optional existing room.",
    "enrollment": "Private synthetic student association to a course section for personal schedule and availability.",
    "legacy_calendar_binding": "Explicit period/planning-week association for an undated busy slot or request.",
    "professor_availability": "Bounded weekly published office-hour patterns and date exceptions.",
    "calendar_block": "Private dated unavailable intervals for a university user.",
    "appointment": "Dated organizer request, duration, current revision and lifecycle state.",
    "appointment_professor": "Required professor decisions for the appointment revision.",
    "appointment_invitation": "Optional student participation status; no mandatory acceptance.",
    "appointment_commitment": "Confirmed mandatory-person reservations with half-open overlap exclusion.",
    "appointment_event": "Participant-visible, timestamped appointment lifecycle history.",
    "faculty_room_approver": "Current designated administrative account for a room-owning faculty.",
    "room_policy": "Explicit owning faculty, bookability, permitted categories and whitelist policy.",
    "room_access": "Allowed university users for explicitly restricted student rooms.",
    "room_closure": "Dated room unavailability, independent of private request details.",
    "student_room_request": "Student needs, selected verified room, faculty approval, dated interval and revision.",
    "room_invitation": "Optional professor attendance response for the current room request revision.",
    "room_reservation": "Exact confirmed exclusive room interval; GiST overlap exclusion.",
    "room_organizer_commitment": "Confirmed organizing-student interval with cross-appointment conflict protection.",
    "room_event": "Private timestamped room request lifecycle and invitation history.",
    "group_meeting_availability": "Owner-published weekly hard availability for the synthetic meeting pilot, with date bounds, relocation opt-in and optimistic revision.",
    "group_meeting": "Persistent synthetic pilot meeting with an accountable organizer, a dated revision, an optional approved room link and at most one move target.",
    "group_meeting_participant": "One required host, required attendee or optional invitee identity per meeting with a current revision response.",
    "group_meeting_commitment": "Exact interval reserved for each confirmed required participant. Optional invitees have no commitment row.",
    "group_meeting_consent": "Explicit revision-scoped move decision by each required participant affected by the proposed replacement.",
    "group_meeting_event": "Participant-scoped lifecycle, confirmation and relocation history for the pilot inbox.",
    "notification": "Recipient-scoped event inbox and durable read state with exactly one appointment, room, equipment, feedback, eligibility or group meeting event.",
    "equipment_category": "Extensible named equipment categories, independent of room types.",
    "equipment_custodian": "One current designated equipment staff/administrator account per owning faculty.",
    "equipment_type": "Faculty-owned equipment catalog, exact specifications and configurable borrowing policy.",
    "equipment_unit": "Individually identifiable physical asset and current physical condition.",
    "borrow_request": "Student borrowing interval, purpose, lifecycle and idempotent submission identity.",
    "borrow_item": "Same-faculty requested type, quantity and exact additional specifications.",
    "equipment_reservation": "Specific reserved asset, excluded overlapping interval, physical handover and verified return.",
    "borrow_extension": "Explicit custodian decision on a proposed later due date for an active loan.",
    "equipment_event": "Actor/time/faculty-scoped inventory, configuration and borrowing lifecycle audit.",
}
GROUP_MEETING_TABLES = {"group_meeting", "group_meeting_availability", "group_meeting_participant",
                        "group_meeting_commitment", "group_meeting_consent", "group_meeting_event"}
MAIN_TABLES = {"role", "organization_unit", "university_user", "resource", "resource_request",
               "busy_slot", "allocation_run", "request_decision", "allocation", "application_state", "request_history"}
MAIN_TABLES |= {"login_account", "academic_period", "legacy_calendar_binding", "appointment", "appointment_professor",
                "appointment_invitation", "appointment_commitment", "professor_availability", "calendar_block"}
MAIN_TABLES |= {"room_policy", "faculty_room_approver", "student_room_request", "room_reservation", "room_invitation", "room_organizer_commitment"}
MAIN_TABLES |= GROUP_MEETING_TABLES
MAIN_TABLES.add("notification")
MAIN_TABLES.add("logged_out_session")
MAIN_TABLES |= {"course_import", "course", "course_section", "teaching_assignment", "course_session", "enrollment"}
MAIN_TABLES |= {'request_eligibility','eligibility_event','allocation_eligibility'}
MAIN_TABLES.add("scheduling_preference_revision")
MAIN_TABLES |= {'scheduling_cost_policy_revision', 'scheduling_cost_policy_event',
                'scheduling_cost_policy_head', 'scheduling_cost_policy_authority_revision'}
MAIN_TABLES |= {'reservation_series','reservation_occurrence','reservation_priority_override'}
MAIN_TABLES.add("waiting_list_entry")
MAIN_TABLES |= {'resource_feedback', 'feedback_event'}
MAIN_TABLES |= {"equipment_category", "equipment_type", "equipment_unit", "equipment_custodian", "borrow_request", "borrow_item", "equipment_reservation", "borrow_extension", "equipment_event"}


def kind(column):
    return "timestamptz" if getattr(column.type, "timezone", False) else str(column.type).lower().replace("(", "_").replace(")", "").replace(" ", "_")


def unique_sets(table):
    return [set(constraint.columns.keys()) for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)] + [set(table.primary_key.columns.keys())]


def er_source(tables, physical):
    lines = ["%% Generated by scripts/generate_database_diagrams.py; do not edit manually.", "erDiagram", "    direction LR"]
    for table in tables:
        lines.append("    " + table.name + " {")
        columns = list(table.columns) if physical else [column for column in table.columns if column.primary_key or column.foreign_keys]
        for column in columns:
            keys = []
            if column.primary_key:
                keys.append("PK")
            if column.foreign_keys:
                keys.append("FK")
            if not column.primary_key and {column.name} in unique_sets(table):
                keys.append("UK")
            suffix = " " + ",".join(keys) if keys else ""
            notes = []
            if column.nullable:
                notes.append("nullable")
            if column.identity is not None:
                notes.append("identity")
            lines.append(f"        {kind(column)} {column.name}{suffix}" + (' "' + "; ".join(notes) + '"' if notes else ""))
        lines.append("    }")
    names = {table.name for table in tables}
    if physical:
        # Alembic's existing infrastructure table is not an application model.
        lines += ["    alembic_version {", "        varchar_32 version_num PK", "    }"]
    for table in tables:
        for fk in sorted(table.foreign_key_constraints, key=lambda item: ",".join(item.columns.keys())):
            parent = fk.referred_table.name
            if parent not in names:
                continue
            left = "o|" if any(column.nullable for column in fk.columns) else "||"
            right = "o|" if set(fk.columns.keys()) in unique_sets(table) or table.name == "application_state" else "|{" if table.name == "request_slot" else "o{"
            label = "_".join(fk.columns.keys())
            lines.append(f"    {parent} {left}--{right} {table.name} : {label}")
    return "\n".join(lines) + "\n"


def catalog(tables):
    lines = ["# Physical schema catalog", "", f"Generated from SQLAlchemy metadata. `alembic_version` is migration infrastructure, not one of the {len(tables)} application tables.",
             "", "Foreign keys use PostgreSQL **NO ACTION** unless explicitly marked RESTRICT; no implicit cascading deletion. Nullable columns are explicitly listed; all others are NOT NULL.",
             "ORM Python defaults are not server defaults. SQL import/admin tools must supply required values unless an identity/server default is listed.", ""]
    for table in tables:
        lines += ["## " + table.name, "", PURPOSES[table.name], "", "| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |", "|---|---|---|---|---|"]
        for column in table.columns:
            keys = ["PK"] if column.primary_key else []
            keys += ["FK -> " + fk.target_fullname for fk in sorted(column.foreign_keys, key=lambda fk: fk.target_fullname)]
            default = "identity" if column.identity is not None else "computed: " + str(column.computed.sqltext) if column.computed is not None else str(column.server_default.arg) if column.server_default is not None else "ORM: " + str(column.default.arg) if column.default is not None and not column.default.is_callable else "ORM callable" if column.default is not None else "-"
            sql_type = column.type.compile(dialect=postgresql.dialect()).lower()
            lines.append(f"| {column.name} | {sql_type} | {'; '.join(keys) or '-'} | {'yes' if column.nullable else 'no'} | {default} |")
        lines += ["", "- Primary key: `" + ", ".join(table.primary_key.columns.keys()) + "`."]
        for fk in sorted(table.foreign_key_constraints, key=lambda item: ",".join(item.columns.keys())):
            lines.append("- Foreign key: `(" + ", ".join(fk.columns.keys()) + ") -> " + fk.referred_table.name
                         + " (" + ", ".join(element.column.name for element in fk.elements) + ")`; " + (fk.ondelete or "NO ACTION") + ".")
        for constraint in sorted(table.constraints, key=lambda item: (type(item).__name__, str(getattr(item, "sqltext", "")), ",".join(item.columns.keys()))):
            if isinstance(constraint, UniqueConstraint):
                lines.append("- Unique: `" + ", ".join(constraint.columns.keys()) + "`.")
            elif hasattr(constraint, "sqltext"):
                lines.append("- Check: `" + str(constraint.sqltext) + "`.")
        for index in sorted(table.indexes, key=lambda item: item.name):
            lines.append("- Index: `" + index.name + " (" + ", ".join(index.columns.keys()) + ")`.")
        lines.append("")
    lines += ["## Confirmed appointment overlap protection", "",
              "Revision `0042a` uses PostgreSQL btree_gist and an exclusion constraint on `(user_id WITH =, period WITH &&)` in `appointment_commitment`. The generated timestamp range is `[start_at, end_at)`; adjacent reservations are allowed. Cancellation releases commitment rows while appointment/history records remain.", ""]
    lines += ["## Group meeting pilot integrity", "",
              "Revision `0051f` adds six tables and links group events to the existing private notification inbox.",
              "The pilot serializes confirmation under the calendar lock. Deferred constraints require the current required approvals and exact participant commitment rows. A GiST exclusion forbids overlapping group meeting commitments for a person.",
              "One active group meeting may link to a room request. The already approved room interval is reused. Deferred protection prevents the release of that room while its linked meeting is confirmed.",
              "Downgrade requires an empty group meeting and hard-availability history. See the [pilot architecture and permission matrix](../research/cdmcs-rehearsal/group-meeting-architecture.md).", ""]
    lines += ["## alembic_version (infrastructure)", "", "Alembic's existing revision marker, not an additional application entity.", "",
              "| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |", "|---|---|---|---|---|",
              "| version_num | varchar(32) | PK | no | - |", "", "No foreign keys, additional indexes or cascading deletion.", ""]
    lines += ["## Deferred request subtype integrity", "",
              "Revision `0041d` adds commit-time constraint triggers to `resource_request`, `request_slot`, `exam_details` and `request_participant`.",
              "Every request has 1-10000 slots; non-recurring requests have exactly one. Exam details exist if and only if the request is an Exam. Participant mappings belong only to CommitteeMeeting requests (an empty committee remains a valid rejected engine input).",
              "Before child writes, a no-op parent revision update serializes each request aggregate and prevents concurrent child-table write skew, including under repeatable read. The triggers do not evaluate allocation rules or increment the application input revision.",
              "SQLAlchemy metadata/Alembic drift checks do not inspect SQL functions; dedicated live tests verify these migration-owned triggers. The physical diagram shows at least one request slot; subtype-specific cardinality is conditional.", ""]
    return "\n".join(lines)


def artifacts():
    tables = sorted(Base.metadata.tables.values(), key=lambda item: item.name)
    if set(PURPOSES) != set(Base.metadata.tables):
        raise RuntimeError("Update table purpose inventory before generating diagrams.")
    return {"database-er-physical.mmd": er_source(tables, True),
            "database-er-high-level.mmd": er_source([item for item in tables if item.name in MAIN_TABLES], False),
            "group-meeting-er.mmd": er_source([item for item in tables if item.name in GROUP_MEETING_TABLES | {
                'university_user', 'student_room_request', 'room_reservation', 'notification'}], False),
            "waiting-list-er.mmd": er_source([item for item in tables if item.name in {
                'waiting_list_entry', 'student_room_request', 'borrow_request', 'university_user',
                'login_account', 'organization_unit','reservation_priority_override'}], True),
            "feedback-er.mmd": er_source([item for item in tables if item.name in {
                'resource_feedback', 'feedback_event', 'notification', 'student_room_request',
                'equipment_reservation', 'university_user', 'organization_unit'}], False),
            "equipment-er.mmd": er_source([item for item in tables if item.name.startswith(('equipment_', 'borrow_'))
                                          or item.name in {'organization_unit', 'university_user', 'login_account', 'notification',
                                              'reservation_series','reservation_occurrence','student_room_request','academic_period','reservation_priority_override'}], False),
            "database-schema-catalog.md": catalog(tables)}


def graphviz_source(physical):
    """Render the same metadata using a local Graphviz/Viz.js tool, without browser tools."""
    tables = sorted((table for table in Base.metadata.tables.values()
                     if physical or table.name in MAIN_TABLES), key=lambda table: table.name)
    lines = ['digraph schema {',
             'graph [rankdir=LR, bgcolor="white", nodesep=.25, ranksep=1.5];',
             'node [shape=Mrecord, fontname="Helvetica", fontsize=10, style=filled, fillcolor="#f1f6f7"];',
             'edge [fontname="Helvetica", fontsize=8, color="#83999f"];']
    for table in tables:
        columns = [column for column in table.columns if physical or column.primary_key or column.foreign_keys]
        fields = []
        for column in columns:
            keys = (' PK' if column.primary_key else '') + (' FK' if column.foreign_keys else '')
            fields.append(f'{column.name}: {kind(column)}{keys}' + (' nullable' if column.nullable else ''))
        label = json.dumps('{' + table.name + '|' + '\\l'.join(fields) + '\\l}').replace(r'\\l', r'\l')
        lines.append(json.dumps(table.name) + ' [label=' + label + '];')
    if physical:
        lines.append('alembic_version [label="{alembic_version|version_num: varchar_32 PK}"];')
    names = {table.name for table in tables}
    for table in tables:
        for fk in sorted(table.foreign_key_constraints, key=lambda item: ','.join(item.columns.keys())):
            if fk.referred_table.name not in names:
                continue
            parent = '0..1' if any(column.nullable for column in fk.columns) else '1'
            children = '0..1' if set(fk.columns.keys()) in unique_sets(table) or table.name == 'application_state' else '1..*' if table.name == 'request_slot' else '0..*'
            lines.append(json.dumps(fk.referred_table.name) + ' -> ' + json.dumps(table.name)
                         + ' [label=' + json.dumps(','.join(fk.columns.keys()))
                         + ',taillabel=' + json.dumps(parent) + ',headlabel=' + json.dumps(children) + '];')
    return '\n'.join([*lines, '}']) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--graphviz", choices=('physical', 'high-level'), help='Write DOT to stdout for an installed SVG renderer')
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent.parent / "docs/architecture")
    args = parser.parse_args()
    if args.graphviz:
        print(graphviz_source(args.graphviz == 'physical'), end='')
        return 0
    stale = []
    for name, contents in artifacts().items():
        path = args.output_dir / name
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != contents:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
    if stale:
        print("Outdated schema documentation: " + ", ".join(stale), file=sys.stderr)
        return 1
    print(f"Schema sources/catalog match all {len(Base.metadata.tables)} application tables.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
