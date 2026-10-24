#include "BestFitSelection.h"
#include <algorithm>
#include <limits>

namespace {
    struct BestFitState {
        bool reachable = false;
        int roomCount = std::numeric_limits<int>::max();
    };
}

std::vector<std::size_t> best_fit::selectCapacityIndices(const std::vector<int>& capacities, int demand) {
    int totalCapacity = 0;
    for (int capacity : capacities) {
        totalCapacity += capacity;
    }
    if (demand <= 0 || totalCapacity < demand) {
        return {};
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
