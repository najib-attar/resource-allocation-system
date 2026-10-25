#include "test_framework.h"
#include "../src/utils/BestFitSelection.h"
#include <limits>

namespace {
    template <typename Error>
    void refuses(const std::vector<int>& capacities) {
        bool refused = false;
        try {
            best_fit::selectCapacityIndices(capacities, 1);
        } catch (const Error&) {
            refused = true;
        }
        CHECK(refused);
    }
}

TEST_CASE("Best-fit rejects nonpositive candidate capacities") {
    refuses<std::invalid_argument>({0});
    refuses<std::invalid_argument>({-1});
    refuses<std::invalid_argument>({10, 0});
}

TEST_CASE("Best-fit checks capacity sums and state count before integer overflow") {
    const int maximum = std::numeric_limits<int>::max();
    refuses<std::length_error>({maximum});
    refuses<std::length_error>({maximum, 1});
    refuses<std::length_error>({maximum / 2, maximum / 2, 2});
    CHECK(best_fit::selectCapacityIndices({maximum, maximum}, 0).empty());
}

TEST_CASE("Best-fit refuses excessive DP memory and work before allocating") {
    refuses<std::length_error>({10000000});
    refuses<std::length_error>(std::vector<int>(7100, 1));
    CHECK(best_fit::selectCapacityIndices(std::vector<int>(10000, 1), 10001).empty());
}

TEST_CASE("Best-fit bounded inputs preserve objective ordering and deterministic ties") {
    const auto selected = best_fit::selectCapacityIndices(std::vector<int>(100, 100), 5000);
    CHECK_EQ(selected.size(), std::size_t(50));
    for (std::size_t index = 0; index < selected.size(); ++index) {
        CHECK_EQ(selected[index], index);
    }
}
