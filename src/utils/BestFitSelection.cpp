#include "BestFitSelection.h"
#include <algorithm>
#include <limits>
#include <stdexcept>

namespace {
    struct BestFitState {
        bool reachable = false;
        int roomCount = std::numeric_limits<int>::max();
    };
    constexpr std::size_t memoryBudget = 64 * 1024 * 1024;
    constexpr std::size_t decisionBudget = 50000000;
}

std::vector<std::size_t> best_fit::selectCapacityIndices(const std::vector<int>& capacities, int demand) {
    if (demand <= 0) {
        return {};
    }
    int totalCapacity = 0;
    for (int capacity : capacities) {
        if (capacity <= 0) {
            throw std::invalid_argument("Best-fit candidate capacities must be positive");
        }
        if (capacity > (std::numeric_limits<int>::max() - 1) - totalCapacity) {
            throw std::length_error("Best-fit capacity total exceeds supported integer range");
        }
        totalCapacity += capacity;
    }
    if (totalCapacity < demand) {
        return {};
    }

    const auto columns = static_cast<std::size_t>(totalCapacity) + 1;
    // Conservative: budget one byte per choice, even though vector<bool> packs bits.
    // Divide before multiplying so both the estimate and the DP stay bounded.
    const auto rowBytes = columns + sizeof(std::vector<bool>) + sizeof(std::size_t);
    if (columns > memoryBudget / sizeof(BestFitState) ||
        capacities.size() > decisionBudget / columns ||
        capacities.size() > (memoryBudget - columns * sizeof(BestFitState)) / rowBytes) {
        throw std::length_error("Best-fit selection exceeds safe computation limits (64 MiB / 50000000 decisions)");
    }
    std::vector<BestFitState> dp(totalCapacity + 1);
    // Stage-indexed choices survive later updates to the one-dimensional scores.
    std::vector<std::vector<bool>> takeRoom(
        capacities.size(), std::vector<bool>(totalCapacity + 1, false));
    dp[0].reachable = true;
    dp[0].roomCount = 0;

    for (std::size_t index = 0; index < capacities.size(); ++index) {
        const int roomCapacity = capacities[index];
        for (int capacity = totalCapacity - roomCapacity; capacity >= 0; --capacity) {
            if (!dp[capacity].reachable) {
                continue;
            }
            const int nextCapacity = capacity + roomCapacity;
            const int nextRoomCount = dp[capacity].roomCount + 1;
            if (!dp[nextCapacity].reachable || nextRoomCount < dp[nextCapacity].roomCount) {
                dp[nextCapacity].reachable = true;
                dp[nextCapacity].roomCount = nextRoomCount;
                takeRoom[index][nextCapacity] = true;
            }
        }
    }

    int bestCapacity = -1;
    for (int capacity = demand; capacity <= totalCapacity; ++capacity) {
        if (dp[capacity].reachable) {
            bestCapacity = capacity;
            break;
        }
    }
    if (bestCapacity < 0) {
        return {};
    }

    std::vector<std::size_t> selected;
    int currentCapacity = bestCapacity;
    for (std::size_t index = capacities.size(); index > 0 && currentCapacity > 0; --index) {
        if (!takeRoom[index - 1][currentCapacity]) {
            continue;
        }
        selected.push_back(index - 1);
        currentCapacity -= capacities[index - 1];
    }
    if (currentCapacity != 0) {
        return {};
    }
    std::reverse(selected.begin(), selected.end());
    return selected;
}
