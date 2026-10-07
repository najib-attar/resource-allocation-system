#ifndef JSONENGINEPROTOCOL_H
#define JSONENGINEPROTOCOL_H

#include <istream>
#include <ostream>
#include "../vendor/nlohmann/json.hpp"

namespace JsonEngineProtocol {
    constexpr int Version = 1;
    nlohmann::json execute(const nlohmann::json& input);
    int run(std::istream& input, std::ostream& output, std::ostream& diagnostics);
}

#endif
