#ifndef BESTFITSELECTION_H
#define BESTFITSELECTION_H

#include <cstddef>
#include <vector>

namespace best_fit {
    // Positive capacities in candidate order; minimize total capacity, then count.
    // Equal-score ties retain the first-discovered selection, in original order.
    std::vector<std::size_t> selectCapacityIndices(const std::vector<int>& capacities, int demand);
}

#endif
