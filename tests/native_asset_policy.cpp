// SPDX-License-Identifier: MIT
// Isolated: no viewer, network, user files, or live inventory.
#include "../viewer-extension/fsmcpassetpolicy.h"
#include <cassert>
#include <iostream>
int main() {
    using namespace fsmcp;
    assert(sameSession(true, "a", "agni", "g1", "a", "agni", "g1"));
    assert(!sameSession(false, "a", "agni", "g1", "a", "agni", "g1"));
    assert(!sameSession(true, "b", "agni", "g1", "a", "agni", "g1"));
    assert(!sameSession(true, "a", "aditi", "g1", "a", "agni", "g1"));
    assert(!sameSession(true, "a", "opensim", "g1", "a", "agni", "g1"));
    // Region/capability changes rotate generation even if account remains unchanged.
    assert(!sameSession(true, "a", "agni", "g2", "a", "agni", "g1"));
    assert(zeroCost(0, 0, 0));
    assert(!zeroCost(0, -1, 0)); assert(!zeroCost(0, 10, 0));
    assert(!zeroCost(0, 0, std::nullopt)); assert(!zeroCost(0, 0, 10));
    assert(!zeroCost(0, 0, -1)); assert(!zeroCost(1, 0, 0));
    // Benefits changing after quote cannot pass the pre-byte check.
    int benefits = 0; assert(zeroCost(0, benefits, 0)); benefits = 10;
    assert(!zeroCost(0, benefits, 0));
    assert(completeInventory(true, 3, 0, 0, 0));
    assert(completeInventory(true, 3, 3, 1, 2));
    assert(!completeInventory(true, 3, 3, 0, 2));
    assert(!completeInventory(true, -1, 0, 0, 0));
    assert(!completeInventory(false, 3, 0, 0, 0));
    assert(!completeInventory(true, 3, -1, 0, 0));
    assert(!completeInventory(true, 3, 10001, 0, 10001));
    assert(canDeliver(true, false, true, true));
    assert(!canDeliver(false, false, true, true)); assert(!canDeliver(true, true, true, true));
    assert(!canDeliver(true, false, false, true)); assert(!canDeliver(true, false, true, false));
    assert(std::string(interruptedState(false, true)) == "cancelled");
    assert(std::string(interruptedState(false, false)) == "failed");
    assert(std::string(interruptedState(true, true)) == "unknown");
    assert(std::string(interruptedState(true, false)) == "unknown");
    std::cout << "30 native policy assertions passed (isolated; no simulator evidence)\n";
}
