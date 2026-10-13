#ifndef APPOINTMENT_JSON_PROTOCOL_H
#define APPOINTMENT_JSON_PROTOCOL_H
#include <iosfwd>
class AppointmentJsonProtocol {
public:
    static int run(std::istream& input, std::ostream& output, std::ostream& diagnostics);
};
#endif
