"""Archived file-publication adapter for historical regression fixtures, not web use."""

from web.backend_result_adapter import BackendResultAdapter
from web.engine_gateway import validate_result
from web.engine_result_projection import result_tables
from web.result_table_schema import INPUT_FILES, OUTPUT_HEADERS
from legacy_shared_file_state import SharedFileState


class LegacyResultAdapter(BackendResultAdapter):
    def pin(self, state=None):
        if state is None:
            with SharedFileState(self.data_dir).locked() as state:
                return self.pin(state)
        pinned = LegacyResultAdapter(self.data_dir, self.raw_data_files)
        document = state.read_engine_result()
        pinned.generation_dir = state.current_data_dir() if document is None else None
        result_reader = BackendResultAdapter(pinned.generation_dir or self.data_dir, self.raw_data_files)
        pinned._tables = {
            name: (result_reader if name in OUTPUT_HEADERS else self).read_csv_table(name)
            for name in (*INPUT_FILES, *(OUTPUT_HEADERS if document is None else ())) if name.endswith(".csv")
        }
        pinned._texts = {"config.txt": self.read_text_file("config.txt")}
        if document is not None:
            validate_result(document["result"], document["snapshot"])
            pinned.engine_result = document["result"]
            pinned._tables.update(result_tables(document["snapshot"], document["result"]))
        return pinned
