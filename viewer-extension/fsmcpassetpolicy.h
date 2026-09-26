// SPDX-License-Identifier: MIT
// Pure invariants shared by the native API and its isolated C++ acceptance test.
#pragma once
#include <string>
#include <optional>
#include <cstddef>
namespace fsmcp {
inline bool sameSession(bool ready, const std::string& avatar, const std::string& grid,
    const std::string& generation, const std::string& expectedAvatar,
    const std::string& expectedGrid, const std::string& expectedGeneration) {
    return ready && !avatar.empty() && !generation.empty() && avatar == expectedAvatar &&
        grid == expectedGrid && generation == expectedGeneration;
}
inline bool zeroCost(int expected, int benefits, std::optional<int> quote) {
    return expected == 0 && benefits == 0 && quote.has_value() && *quote == 0;
}
inline bool completeInventory(bool ownerMatches, int version, int declared, size_t folders, size_t items) {
    return ownerMatches && version >= 0 && declared >= 0 && declared <= 10000 &&
        folders <= 10000 && items <= 10000 && folders + items == static_cast<size_t>(declared);
}
inline bool canDeliver(bool ownerMatches, bool groupOwned, bool canCopy, bool populated) {
    return ownerMatches && !groupOwned && canCopy && populated;
}
inline const char* interruptedState(bool submitted, bool cancelled) {
    return submitted ? "unknown" : cancelled ? "cancelled" : "failed";
}
}
