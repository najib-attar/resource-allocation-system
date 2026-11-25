"""Add normalized course catalogs, sections, teaching sessions and enrollments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0051e"
down_revision = "0051d"
branch_labels = depends_on = None


def upgrade():
    op.create_table("course_import",
        sa.Column("academic_period_id", sa.Integer(), sa.ForeignKey("academic_period.id"), primary_key=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("supplement_sha256", sa.String(64)),
        sa.Column("provenance", JSONB(), nullable=False),
        sa.Column("report", JSONB(), nullable=False))
    op.create_table("course",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.CheckConstraint("length(btrim(code)) > 0 AND length(btrim(title)) > 0", name="ck_course_identity"))
    op.create_table("course_section",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("course.id"), nullable=False),
        sa.Column("academic_period_id", sa.Integer(), sa.ForeignKey("academic_period.id"), nullable=False),
        sa.Column("crn", sa.String(24), nullable=False),
        sa.Column("published_title", sa.Text(), nullable=False),
        sa.Column("branch", sa.String(24), nullable=False),
        sa.Column("academic_level", sa.String(12), nullable=False),
        sa.Column("instruction_method", sa.Text(), nullable=False),
        sa.Column("quota", sa.Integer()),
        sa.Column("source_kind", sa.String(12), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("publication_status", sa.String(20), nullable=False),
        sa.Column("published_schedule", JSONB(), nullable=False),
        sa.Column("excluded_dates", JSONB(), nullable=False),
        sa.UniqueConstraint("academic_period_id", "crn"),
        sa.CheckConstraint("quota IS NULL OR quota >= 0", name="ck_course_section_quota"),
        sa.CheckConstraint("source_kind IN ('archive','obs')", name="ck_course_section_source"),
        sa.CheckConstraint("publication_status IN ('scheduled','unpublished')", name="ck_course_section_status"))
    op.create_index("ix_course_section_course_id", "course_section", ["course_id"])
    op.create_table("teaching_assignment",
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("course_section.id"), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("university_user.id")),
        sa.Column("published_name", sa.Text(), nullable=False),
        sa.CheckConstraint("ordinal > 0 AND length(btrim(published_name)) > 0", name="ck_teaching_assignment_identity"))
    op.create_index("ix_teaching_assignment_user_id", "teaching_assignment", ["user_id"])
    op.create_table("course_session",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("course_section.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("resource.id")),
        sa.Column("building_code", sa.Text()),
        sa.Column("room_code", sa.Text()),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("start_minutes", sa.Integer(), nullable=False),
        sa.Column("end_minutes", sa.Integer(), nullable=False),
        sa.Column("published_day", sa.Text()),
        sa.Column("published_start", sa.String(5)),
        sa.Column("published_end", sa.String(5)),
        sa.Column("published_building", sa.Text()),
        sa.Column("published_room", sa.Text()),
        sa.Column("valid_until", sa.Date()),
        sa.UniqueConstraint("section_id", "ordinal"),
        sa.CheckConstraint("ordinal > 0 AND day BETWEEN 1 AND 7 AND start_minutes >= 0 "
                           "AND start_minutes < end_minutes AND end_minutes <= 1440", name="ck_course_session_time"))
    op.create_index("ix_course_session_resource_id", "course_session", ["resource_id"])
    op.create_table("enrollment",
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("course_section.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("university_user.id"), primary_key=True))
    op.create_index("ix_enrollment_user_id", "enrollment", ["user_id"])


def downgrade():
    tables = ("enrollment", "course_session", "teaching_assignment", "course_section", "course", "course_import")
    op.execute("LOCK TABLE " + ", ".join(tables) + " IN ACCESS EXCLUSIVE MODE")
    if any(op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")) for table in tables):
        raise RuntimeError("Cannot discard an existing course catalog or enrollments.")
    for table in tables:
        op.drop_table(table)
