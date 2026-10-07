#ifndef CSVREADER_H
#define CSVREADER_H

#include <istream>
#include <string>
#include <vector>

class CsvReader {
public:
    enum class Result { Record, End, Malformed };

    explicit CsvReader(std::istream& input);
    Result readRecord(std::vector<std::string>& fields, std::string& error);
    size_t getRecordNumber() const;

private:
    std::istream& input;
    size_t recordNumber = 0;
    bool finished = false;
};

#endif
