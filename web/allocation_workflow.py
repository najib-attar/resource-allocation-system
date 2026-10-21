"""Run the existing engine outside database transactions, then publish atomically."""

from sqlalchemy.exc import SQLAlchemyError

from .backend_executable import BackendExecutableError
from .engine_gateway import EngineIntegrationError
from .persistence.database import DatabaseBusy
from .persistence.repository import PersistenceError, StaleRun


def execute_allocation(repository, gateway, logger=None):
    run_id, snapshot = repository.start_run()
    try:
        result, metadata = gateway.execute(snapshot)
        repository.publish_run(run_id, result, metadata)
    except (EngineIntegrationError, BackendExecutableError, PersistenceError, DatabaseBusy, SQLAlchemyError) as error:
        message = "Database publication failed; previous results remain active." if isinstance(error, SQLAlchemyError) else str(error)
        try:
            repository.fail_run(run_id, message, superseded=isinstance(error, StaleRun))
        except (SQLAlchemyError, DatabaseBusy) as record_error:
            if logger:
                logger.error("Could not record failed run %s (%s). Previous results were not replaced.", run_id, type(record_error).__name__)
        raise
    # Academic publication can release room occupancy. It has already committed;
    # a queue-engine failure must not misreport that successful publication as failed.
    from .waiting_list_service import WaitingListService
    from .calendar_service import CalendarError
    import logging
    try:
        WaitingListService(repository.database, gateway).refresh_all('room')
    except (CalendarError, EngineIntegrationError, SQLAlchemyError, DatabaseBusy):
        (logger or logging.getLogger(__name__)).exception('Academic results were published, but waiting-list reevaluation needs a retry.')
    return result
