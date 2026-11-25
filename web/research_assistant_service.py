"""Private research task planning and a bounded assistant dashboard."""

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .account_service import is_research_assistant
from .notification_service import _visible
from .personal_schedule_service import read_schedule, select_calendar
from .persistence.models import LoginAccount, ResearchTask, Role, User


class ResearchTaskError(ValueError):
    status = 400


class ResearchTaskConflict(ResearchTaskError):
    status = 409


class ResearchTaskMissing(ResearchTaskError):
    status = 404


def task_selection(state, page):
    if state not in ("open", "completed", "all") or type(page) is not int or not 1 <= page <= 10000:
        raise ResearchTaskError("Choose a valid task filter and page.")
    return state, page


def _values(title, due_date):
    title = title.strip() if isinstance(title, str) else ""
    if not 1 <= len(title) <= 160 or any(ord(character) < 32 for character in title):
        raise ResearchTaskError("Enter a single-line task title of 1 to 160 characters.")
    if due_date in (None, ""):
        return title, None
    try:
        due = date.fromisoformat(due_date)
        if due.isoformat() != due_date:
            raise ValueError()
    except (TypeError, ValueError) as error:
        raise ResearchTaskError("Choose a valid due date or leave it blank.") from error
    return title, due


def _task_id(value):
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (AttributeError, ValueError, TypeError) as error:
        raise ResearchTaskError("This task form has expired. Open the planner and try again.") from error


def _serialize(task):
    return dict(id=task.id, title=task.title, due=task.due_date,
                completed=task.completed_at is not None, revision=task.revision)


class ResearchAssistantService:
    PAGE_SIZE = 25

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _require(session, actor, *, lock=False):
        if type(actor) is not int or not 1 <= actor <= 2147483647:
            raise PermissionError("Research Assistant access required.")
        query = select(User, Role.name).join(Role, Role.id == User.primary_role_id).join(
            LoginAccount, LoginAccount.user_id == User.id).where(
            User.id == actor, LoginAccount.enabled.is_(True), func.lower(User.status) == "active")
        if lock:
            query = query.with_for_update(read=True, of=(User, LoginAccount))
        row = session.execute(query).one_or_none()
        if row is None or not is_research_assistant(row[1], row[0].assistant_type):
            raise PermissionError("Research Assistant access required.")
        return row[0]

    @staticmethod
    def _ordered(actor):
        return select(ResearchTask).where(ResearchTask.owner_id == actor).order_by(
            ResearchTask.completed_at.is_not(None), ResearchTask.due_date.asc().nulls_last(),
            ResearchTask.created_at.desc(), ResearchTask.id.desc())

    @staticmethod
    def _locked_task(session, actor, key):
        task = session.get(ResearchTask, (actor, _task_id(key)), with_for_update=True)
        if task is None:
            raise ResearchTaskMissing("This task is unavailable.")
        return task

    @staticmethod
    def _check_revision(task, revision):
        if type(revision) is not int or not 1 <= revision <= 2147483647:
            raise ResearchTaskError("Open the planner and try again with a current task revision.")
        if task.revision != revision:
            raise ResearchTaskConflict("This task changed. Review its current version before saving.")

    def home(self, actor):
        with self.database.transaction(read_only=True) as session:
            assistant = self._require(session, actor)
            open_tasks = self._ordered(actor).where(ResearchTask.completed_at.is_(None))
            count = session.scalar(select(func.count()).select_from(open_tasks.order_by(None).subquery()))
            preview = [_serialize(task) for task in session.scalars(open_tasks.limit(4))]
            inbox = _visible(actor)
            unread = session.scalar(select(func.count()).select_from(inbox).where(inbox.c.read_at.is_(None)))
            return dict(name=assistant.name, tasks=preview, open_count=count, unread_count=unread,
                        schedule=read_schedule(session, actor, select_calendar()))

    def tasks(self, actor, *, state="open", page=1):
        state, page = task_selection(state, page)
        with self.database.transaction(read_only=True) as session:
            self._require(session, actor)
            query = self._ordered(actor)
            if state == "open":
                query = query.where(ResearchTask.completed_at.is_(None))
            elif state == "completed":
                query = query.where(ResearchTask.completed_at.is_not(None))
            rows = list(session.scalars(query.offset((page - 1) * self.PAGE_SIZE).limit(self.PAGE_SIZE + 1)))
            return dict(items=[_serialize(task) for task in rows[:self.PAGE_SIZE]],
                        state=state, page=page, has_next=len(rows) > self.PAGE_SIZE)

    def create(self, actor, token, title, due_date=""):
        key = _task_id(token)
        title, due = _values(title, due_date)
        with self.database.transaction() as session:
            self._require(session, actor, lock=True)
            # This form key is scoped to its owner and safe to submit more than once.
            result = session.execute(insert(ResearchTask).values(
                owner_id=actor, id=key, title=title, due_date=due).on_conflict_do_nothing(
                    index_elements=[ResearchTask.owner_id, ResearchTask.id]).returning(ResearchTask.id)).scalar()
            if result is None:
                task = session.get(ResearchTask, (actor, key))
                if (task.title, task.due_date) != (title, due):
                    raise ResearchTaskConflict("This form already saved a task. Start a new task or edit the existing one.")
            return key

    def edit(self, actor, task_id, revision, title, due_date=""):
        title, due = _values(title, due_date)
        with self.database.transaction() as session:
            self._require(session, actor, lock=True)
            task = self._locked_task(session, actor, task_id)
            self._check_revision(task, revision)
            if (task.title, task.due_date) != (title, due):
                task.title, task.due_date = title, due
                task.revision += 1

    def set_state(self, actor, task_id, revision, target):
        if target not in ("complete", "reopen"):
            raise ResearchTaskError("Choose whether to complete or reopen this task.")
        with self.database.transaction() as session:
            self._require(session, actor, lock=True)
            task = self._locked_task(session, actor, task_id)
            # Accept an immediately repeated save of the same transition.
            completed = target == "complete"
            already_set = completed == (task.completed_at is not None)
            if already_set and type(revision) is int and 1 <= revision == task.revision - 1:
                return
            self._check_revision(task, revision)
            if not already_set:
                task.completed_at = datetime.now(timezone.utc) if completed else None
                task.revision += 1
