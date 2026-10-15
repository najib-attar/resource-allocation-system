"""Pin one coherent PostgreSQL view and delegate file-free presentation."""

from .backend_result_adapter import BackendResultAdapter
from .engine_result_projection import input_tables, result_tables
from .result_table_schema import OUTPUT_HEADERS, table_view


class DatabaseResultAdapter(BackendResultAdapter):
    def __init__(self, repository, raw_data_files):
        snapshot, document, self.run_id = repository.read_view()
        tables = input_tables(snapshot)
        tables.update({name: table_view(headers, [], exists=False, message="Allocation has not been run yet.")
                       for name, headers in OUTPUT_HEADERS.items()})
        if document:
            tables.update(result_tables(document["snapshot"], document["result"]))
        super().__init__(tables, raw_data_files, strategy=snapshot["strategy"],
                         engine_result=document["result"] if document else None)
