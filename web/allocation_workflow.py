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
    return result
