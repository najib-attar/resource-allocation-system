#ifndef EQUIPMENT_JSON_PROTOCOL_H
#define EQUIPMENT_JSON_PROTOCOL_H
#include <iosfwd>
class EquipmentJsonProtocol {
public:
    static int run(std::istream& input, std::ostream& output, std::ostream& diagnostics);
};
#endif
