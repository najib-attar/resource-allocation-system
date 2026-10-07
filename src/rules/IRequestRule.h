#ifndef IREQUESTRULE_H
#define IREQUESTRULE_H

#include "../models/Request.h"
#include "../models/Allocation.h"
#include "RuleEvaluationResult.h"

class IRequestRule {
public:
    virtual ~IRequestRule() = default;

    virtual RuleEvaluationResult evaluate(Request& request) const = 0;

    virtual RuleEvaluationResult evaluate(
        Request& request, const std::vector<Allocation>& allocations
    ) const {
        (void)allocations;
        return evaluate(request);
    }
};

#endif
