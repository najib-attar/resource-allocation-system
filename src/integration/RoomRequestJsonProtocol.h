#ifndef ROOM_REQUEST_JSON_PROTOCOL_H
#define ROOM_REQUEST_JSON_PROTOCOL_H
#include <iosfwd>
class RoomRequestJsonProtocol {
public:
    static int run(std::istream& input, std::ostream& output, std::ostream& diagnostics, bool series = false);
};
#endif
