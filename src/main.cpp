#include <iostream>
#include <vector>
#include <cstdio>
#include "models/Request.h"
#include "models/OneTimeRequest.h"
#include "models/RecurringRequest.h"
#include "models/ExamRequest.h"
#include "models/CommitteeMeetingRequest.h"
#include "models/InvalidRequest.h"
#include "models/Allocation.h"
#include "services/ResourceAllocationSession.h"
#include "utils/ConsolePrinter.h"
#include "integration/JsonEngineProtocol.h"
#include "integration/AppointmentJsonProtocol.h"

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string(argv[1]) == "--appointments-json") {
        return AppointmentJsonProtocol::run(std::cin, std::cout, std::cerr);
    }
    if (argc == 2 && std::string(argv[1]) == "--json") {
        return JsonEngineProtocol::run(std::cin, std::cout, std::cerr);
    }
    if (argc != 1) {
        std::cerr << "Usage: allocation_system [--json | --appointments-json]\n";
        return 2;
    }
    ResourceAllocationSession session;
    session.loadStrategyName("data/config.txt");

    if (!session.loadSystemData(
        "data/users.csv",
        "data/spaces.csv",
        "data/requests.csv"
    )) {
        std::remove("data/allocations.csv");
        std::remove("data/request_results.csv");
        std::remove("data/request_summaries.csv");
        std::remove("data/allocation_summaries.csv");
        std::cout << "Error: Failed to load system data.\n";
        std::cout << "Stale output files were cleared.\n";
        session.cleanup();
        return 1;
    }

    SystemData& data = session.getSystemData();

    session.runAllocation();

    for (Request* request : data.requests) {
        if (!request) {
            std::cerr << "Warning: Skipping null request during console reporting.\n";
            continue;
        }

        std::string label = "Request " + std::to_string(request->getId());

        if (OneTimeRequest* oneTime = dynamic_cast<OneTimeRequest*>(request)) {
            bool result = oneTime->getStatus() == RequestStatus::Approved;
            printOneTimeResult(
                label,
                *oneTime,
                result,
                "One-time request loaded from external CSV source"
            );
        }
        else if (RecurringRequest* recurring = dynamic_cast<RecurringRequest*>(request)) {
            bool result = recurring->getStatus() == RequestStatus::Approved;
            printRecurringResult(
                label,
                *recurring,
                result,
                "Recurring request loaded from external CSV source"
            );
        }
        else if (ExamRequest* exam = dynamic_cast<ExamRequest*>(request)) {
            bool result = exam->getStatus() == RequestStatus::Approved;
            printExamResult(
                label,
                *exam,
                result,
                "Exam request loaded from external CSV source"
            );
        }
        else if (CommitteeMeetingRequest* committee = dynamic_cast<CommitteeMeetingRequest*>(request)) {
            bool result = committee->getStatus() == RequestStatus::Approved;
            printCommitteeMeetingResult(
                label,
                *committee,
                result,
                "Committee meeting request loaded from external CSV source"
            );
        }
        else if (InvalidRequest* invalid = dynamic_cast<InvalidRequest*>(request)) {
            printInvalidResult(
                label,
                *invalid,
                "Invalid request loaded from external CSV source"
            );
        }
    }

    session.printAllocations();

    const bool exportsSucceeded = session.exportResults(
        "data/allocations.csv",
        "data/request_results.csv",
        "data/request_summaries.csv",
        "data/allocation_summaries.csv"
    );

    if (exportsSucceeded) {
        std::cout << "\nAllocations exported to data/allocations.csv\n";
        std::cout << "Request results exported to data/request_results.csv\n";
        std::cout << "Request summaries exported to data/request_summaries.csv\n";
        std::cout << "Allocation summaries exported to data/allocation_summaries.csv\n";
    } else {
        std::cerr << "\nError: One or more output files could not be exported.\n";
    }

    session.cleanup();
    return exportsSucceeded ? 0 : 1;
}
