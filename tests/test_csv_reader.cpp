#include "test_framework.h"
#include "../src/utils/CsvReader.h"
#include <sstream>

TEST_CASE("CSV reader decodes comma quotes empty fields and UTF-8 without shifting columns") {
    std::istringstream input("ordinary,\"Advanced Algorithms, Part II\",\"He said \"\"yes\"\"\",,Jos\xC3\xA9,\r\n");
    CsvReader reader(input);
    std::vector<std::string> fields;
    std::string error;
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
    const std::vector<std::string> expected{"ordinary", "Advanced Algorithms, Part II",
                                           "He said \"yes\"", "", "Jos\xC3\xA9", ""};
    CHECK(fields == expected);
    CHECK(error.empty());
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::End);
}

TEST_CASE("CSV reader preserves embedded LF and CRLF inside quoted fields") {
    std::istringstream input("1,\"first\nsecond\",\"third\r\nfourth\"\r\n2,plain,text\n");
    CsvReader reader(input);
    std::vector<std::string> fields;
    std::string error;
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
    CHECK_EQ(fields.size(), static_cast<size_t>(3));
    CHECK_EQ(fields[1], std::string("first\nsecond"));
    CHECK_EQ(fields[2], std::string("third\r\nfourth"));
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
    CHECK_EQ(fields[0], std::string("2"));
    CHECK_EQ(reader.getRecordNumber(), static_cast<size_t>(2));
}

TEST_CASE("CSV reader accepts final records without a terminating newline") {
    for (const std::string text : {"a,b,", "\"a\",\"b\",\"\""}) {
        std::istringstream input(text);
        CsvReader reader(input);
        std::vector<std::string> fields;
        std::string error;
        CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
        CHECK(fields == std::vector<std::string>({"a", "b", ""}));
        CHECK(reader.readRecord(fields, error) == CsvReader::Result::End);
    }
}

TEST_CASE("CSV reader distinguishes blank records from quoted empty fields") {
    std::istringstream input("\r\n\"\"\n,\r\n");
    CsvReader reader(input);
    std::vector<std::string> fields;
    std::string error;
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
    CHECK(fields.empty());
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
    CHECK(fields == std::vector<std::string>{""});
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
    CHECK(fields == std::vector<std::string>({"", ""}));
}

TEST_CASE("CSV reader handles UTF-8 BOM before quoted headers without consuming other UTF-8") {
    for (const std::string& prefix : {std::string("\xEF\xBB\xBF"), std::string()}) {
        std::istringstream input(prefix + "\"requestId\",\"title\"\n");
        CsvReader reader(input);
        std::vector<std::string> fields;
        std::string error;
        CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
        CHECK(fields == std::vector<std::string>({"requestId", "title"}));
    }
    std::istringstream input("\xEF\xBC\xA1,plain\n");
    CsvReader reader(input);
    std::vector<std::string> fields;
    std::string error;
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
    CHECK_EQ(fields[0], std::string("\xEF\xBC\xA1"));
}

TEST_CASE("CSV reader rejects illegal quotes and resumes after malformed physical records") {
    for (const std::string text : {"1,un\"quoted,value\n", "1,\"closed\"oops,value\r\n",
                                   "1,\"closed\" ,value\n"}) {
        std::istringstream input(text + "2,valid,value\n");
        CsvReader reader(input);
        std::vector<std::string> fields;
        std::string error;
        CHECK(reader.readRecord(fields, error) == CsvReader::Result::Malformed);
        CHECK(!error.empty());
        CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
        CHECK_EQ(fields[0], std::string("2"));
        CHECK_EQ(fields.size(), static_cast<size_t>(3));
    }
}

TEST_CASE("CSV reader rejects unterminated quoted records rather than inventing subsequent rows") {
    std::istringstream input("1,\"never closed\n2,looks,valid\n");
    CsvReader reader(input);
    std::vector<std::string> fields;
    std::string error;
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::Malformed);
    CHECK_CONTAINS(error, "Unterminated quoted field");
    CHECK(reader.readRecord(fields, error) == CsvReader::Result::End);
}

TEST_CASE("CSV reader roundtrips combinations of standard quoted fields") {
    const std::vector<std::string> values{"", "plain", "a,b", "\"", "a\"b", "line\nbreak",
                                          "line\r\nbreak", " leading ", "Jos\xC3\xA9"};
    for (const auto& first : values) {
        for (const auto& second : values) {
            const std::vector<std::string> expected{first, second, ""};
            std::string encoded;
            for (const auto& value : expected) {
                if (!encoded.empty()) encoded += ',';
                encoded += '"';
                for (char ch : value) {
                    encoded += ch;
                    if (ch == '"') encoded += '"';
                }
                encoded += '"';
            }
            std::istringstream input(encoded + "\r\n");
            CsvReader reader(input);
            std::vector<std::string> fields;
            std::string error;
            CHECK(reader.readRecord(fields, error) == CsvReader::Result::Record);
            CHECK(fields == expected);
        }
    }
}
