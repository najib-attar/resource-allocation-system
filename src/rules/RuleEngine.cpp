#include "RuleEngine.h"

RuleEngine::RuleEngine(const std::vector<const IRequestRule*>& requestRules)
    : requestRules(requestRules) {}

RuleEvaluationResult RuleEngine::evaluate(OneTimeRequest& request,
                                          const std::vector<Allocation>& allocations) const {
    for (const IRequestRule* rule : requestRules) {
        RuleEvaluationResult result = rule->evaluate(request);
        if (!result.isPassed()) {
            return result;
        }
    }

    if (!availabilityRule.check(request, allocations)) {
        return RuleEvaluationResult(false, "Time slot unavailable");
    }

    return RuleEvaluationResult(true, "");
}

RuleEvaluationResult RuleEngine::evaluate(RecurringRequest& request,
                                          const std::vector<Allocation>& allocations) const {
    for (const IRequestRule* rule : requestRules) {
        RuleEvaluationResult result = rule->evaluate(request);
        if (!result.isPassed()) {
            return result;
        }
    }

    if (!availabilityRule.check(request, allocations)) {
        return RuleEvaluationResult(false, "Time slot unavailable");
    }

    return RuleEvaluationResult(true, "");
}

RuleEvaluationResult RuleEngine::evaluate(ExamRequest& request,
                                          const std::vector<Allocation>& allocations) const {
    for (const IRequestRule* rule : requestRules) {
        RuleEvaluationResult result = rule->evaluate(request);
        if (!result.isPassed()) {
            return result;
        }
    }

    if (!availabilityRule.check(request, allocations)) {
        return RuleEvaluationResult(false, "Time slot unavailable");
    }

    return RuleEvaluationResult(true, "");
}

RuleEvaluationResult RuleEngine::evaluate(CommitteeMeetingRequest& request,
                                          const std::vector<Allocation>& allocations) const {
    for (const IRequestRule* rule : requestRules) {
        RuleEvaluationResult result = rule->evaluate(request, allocations);
        if (!result.isPassed()) {
            return result;
        }
    }

    if (!availabilityRule.check(request, allocations)) {
        return RuleEvaluationResult(false, "Time slot unavailable");
    }

    return RuleEvaluationResult(true, "");
}
