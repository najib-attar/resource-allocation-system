# Vendored JSON Dependency

Unmodified nlohmann/json **3.12.0**, MIT license (`LICENSE.MIT`).
Only the upstream single header is needed; no runtime library or network build step.

Source: https://github.com/nlohmann/json/tree/v3.12.0

Header URL: https://raw.githubusercontent.com/nlohmann/json/v3.12.0/single_include/nlohmann/json.hpp

Header SHA-256: `aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63`

The repository currently uses recursive G++ build scripts, not CMake. The header
is included relatively by the protocol boundary and is covered by the existing
backend source fingerprint. Future CMake builds can include it without fetching
dependencies or changing domain code.
