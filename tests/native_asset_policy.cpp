// SPDX-License-Identifier: MIT
// Isolated: no viewer, network, user files, or live inventory.
#include "../viewer-extension/fsmcpassetpolicy.h"
#include <cassert>
#include <iostream>
#include <map>
#include <limits>
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
    assert(approvedQuote(10, 10)); assert(approvedQuote(0, 0));
    assert(!approvedQuote(10, 9)); assert(!approvedQuote(10, 11));
    assert(!approvedQuote(10, std::nullopt)); assert(!approvedQuote(-1, -1));
    struct Preparation { std::string lease, generation, bytes; double expires; int cost; };
    std::map<std::string, Preparation> uploads;
    uploads["quote"] = {"lease", "generation", "immutable-encoded-bytes", 300., 10};
    Preparation claimed;
    auto rejected = [&](const std::string& lease, const std::string& generation, double time, std::optional<int> cost) {
        assert(claimUpload(uploads, "quote", lease, generation, time, cost, claimed));
        assert(uploads.size() == 1); // A refusal never changes the pending preparation.
    };
    rejected("other", "generation", 1., 10); rejected("lease", "new-generation", 1., 10);
    rejected("lease", "generation", 300., 10); rejected("lease", "generation", 301., 10);
    rejected("lease", "generation", std::numeric_limits<double>::quiet_NaN(), 10);
    rejected("lease", "generation", 1., std::nullopt); rejected("lease", "generation", 1., 0);
    assert(!claimUpload(uploads, "quote", "lease", "generation", 299., 10, claimed));
    assert(uploads.empty() && claimed.bytes == "immutable-encoded-bytes");
    assert(claimUpload(uploads, "quote", "lease", "generation", 299., 10, claimed));
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
    std::cout << "Native asset policy assertions passed, including upload cost/lease/expiry/single-use guards (isolated; no simulator evidence)\n";
}
