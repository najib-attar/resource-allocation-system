#include "CsvReader.h"

CsvReader::CsvReader(std::istream& input) : input(input) {
    // UTF-8 BOM is a file prefix, not part of the first (possibly quoted) field.
    if (input.peek() == 0xEF) {
        std::string prefix;
        for (int index = 0; index < 3; ++index) {
            const int ch = input.get();
            if (ch == std::char_traits<char>::eof()) break;
            prefix += static_cast<char>(ch);
        }
        if (prefix != "\xEF\xBB\xBF") {
            input.clear();
            for (auto it = prefix.rbegin(); it != prefix.rend(); ++it) input.putback(*it);
        }
    }
}

CsvReader::Result CsvReader::readRecord(std::vector<std::string>& fields, std::string& error) {
    fields.clear();
    error.clear();
    if (finished) return Result::End;

    enum class State { Start, Unquoted, Quoted, Closed };
    State state = State::Start;
    std::string field;
    bool hasCharacters = false;
    ++recordNumber;

    while (true) {
        const int next = input.get();
        if (next == std::char_traits<char>::eof()) {
            finished = true;
            if (input.bad()) {
                error = "CSV input read failure";
                return Result::Malformed;
            }
            if (state == State::Quoted) {
                error = "Unterminated quoted field";
                return Result::Malformed;
            }
            if (!hasCharacters) return Result::End;
            fields.push_back(field);
            return Result::Record;
        }

        const char ch = static_cast<char>(next);
        if (state == State::Quoted) {
            if (ch == '"') {
                if (input.peek() == '"') {
                    input.get();
                    field += '"';
                } else {
                    state = State::Closed;
                }
            } else {
                field += ch;
            }
            continue;
        }

        if (ch == '\n' || ch == '\r') {
            if (ch == '\r' && input.peek() == '\n') input.get();
            if (hasCharacters) fields.push_back(field);
            return Result::Record;
        }

        hasCharacters = true;
        if (ch == ',') {
            fields.push_back(field);
            field.clear();
            state = State::Start;
        } else if (state == State::Start && ch == '"') {
            state = State::Quoted;
        } else if (state == State::Closed || ch == '"') {
            error = state == State::Closed ? "Unexpected character after closing quote"
                                          : "Unexpected quote in unquoted field";
            // These errors occur outside a quoted field; resume at the next physical record.
            while (input.peek() != std::char_traits<char>::eof()) {
                const char discarded = static_cast<char>(input.get());
                if (discarded == '\n') break;
                if (discarded == '\r') {
                    if (input.peek() == '\n') input.get();
                    break;
                }
            }
            return Result::Malformed;
        } else {
            field += ch;
            state = State::Unquoted;
        }
    }
}

size_t CsvReader::getRecordNumber() const {
    return recordNumber;
}
