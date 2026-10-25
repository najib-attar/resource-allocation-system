#ifndef BESTFITSELECTION_H
#define BESTFITSELECTION_H

#include <cstddef>
#include <vector>

namespace best_fit {
    // Positive capacities in candidate order; minimize total capacity, then count.
    // Equal-score ties retain the first-discovered selection, in original order.
    // Invalid capacities throw invalid_argument; unsafe DP sizes throw length_error.
    // Technical limits: conservative 64 MiB allocation estimate, 50M decision cells.
    std::vector<std::size_t> selectCapacityIndices(const std::vector<int>& capacities, int demand);
}

#endif
