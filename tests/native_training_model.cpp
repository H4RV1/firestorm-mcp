// SPDX-License-Identifier: MIT
// Synthetic geometry and clock only. No viewer, network or user state.
#include "../viewer-extension/fsmcptrainingmodel.h"
#include <cassert>
#include <iostream>

int main()
{
    using namespace fsmcp_training;
    const Rules rules;
    const Vec forward{1,0,0};
    const auto inside = evaluate({1.9,0,0},forward,rules);
    const auto outside = evaluate({2.001,0,0},forward,rules);
    assert(inside.eligible());
    assert(evaluate({2,0,0},forward,rules).eligible());
    assert(!outside.eligible());
    assert(!evaluate({-1,0,0},forward,rules).in_front);
    assert(evaluate({0,1,0},forward,rules).in_front);
    // Height is part of the distance, not merely a horizontal radius.
    assert(!evaluate({1.8,0,1},forward,rules).in_range);
    // Facing rotation changes eligibility without changing target distance.
    assert(!evaluate({1,0,0},{-1,0,0},rules).eligible());
    assert(evaluate({1,0,0},{2,0,0},rules).eligible());
    Rules narrow = rules; narrow.half_angle_degrees = 30;
    assert(!evaluate({1,1,0},forward,narrow).in_front);
    Rules sphere = rules; sphere.half_angle_degrees = 180;
    assert(evaluate({-1,0,0},forward,sphere).eligible());
    assert(!evaluate({0,0,0},forward,rules).known);
    assert(!evaluate({1,0,0},{0,0,0},rules).known);
    assert(!evaluate({std::numeric_limits<double>::infinity(),0,0},forward,rules).known);
    Rules invalid = rules; invalid.range = std::numeric_limits<double>::quiet_NaN();
    assert(!invalid.valid()); assert(!evaluate({1,0,0},forward,invalid).known);
    invalid = rules; invalid.cooldown = -1; assert(!invalid.valid());
    Clock clock;
    // A miss consumes the same cooldown as an eligible attempt.
    assert(clock.attempt(10,outside,rules) == Attempt::outside_volume);
    assert(clock.remaining(10) == 2);
    assert(clock.attempt(11.999,inside,rules) == Attempt::cooling_down);
    assert(clock.remaining(12) == 0); // Rejected early input does not extend it.
    assert(clock.attempt(12,inside,rules) == Attempt::eligible);
    assert(clock.attempt(13,{},rules) == Attempt::cooling_down);
    assert(clock.attempt(14,{},rules) == Attempt::unknown);
    assert(clock.remaining(14) == 2); // Unknown target remains unknown, even when timer starts.
    clock.reset(); assert(clock.remaining(14) == 0);
    Rules eligibleOnly=rules; eligibleOnly.eligible_only=true;
    assert(clock.attempt(20,outside,eligibleOnly) == Attempt::outside_volume);
    assert(clock.remaining(20) == 0);
    assert(clock.attempt(20,inside,eligibleOnly) == Attempt::eligible);
    assert(clock.remaining(20) == 2);
    assert(clock.attempt(std::numeric_limits<double>::quiet_NaN(),inside,rules)==Attempt::unknown);
    std::cout << "Training geometry and cooldown checks passed (synthetic, offline)\n";
}
