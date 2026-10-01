// SPDX-License-Identifier: MIT
// Local geometry/timing predictions. No simulator or damage authority.
#pragma once
#include <algorithm>
#include <cmath>
#include <limits>

namespace fsmcp_training
{
constexpr double pi = 3.14159265358979323846;
struct Vec { double x, y, z; };
struct Rules
{
    double range = 2.0;
    double half_angle_degrees = 90.0;
    double cooldown = 2.0;
    bool eligible_only = false;
    bool valid() const
    {
        return std::isfinite(range) && range > 0 && range <= 96 &&
            std::isfinite(half_angle_degrees) && half_angle_degrees > 0 && half_angle_degrees <= 180 &&
            std::isfinite(cooldown) && cooldown >= 0 && cooldown <= 60;
    }
};
struct Geometry
{
    bool known = false, in_range = false, in_front = false;
    double distance = 0, angle_degrees = 0;
    bool eligible() const { return known && in_range && in_front; }
};
inline Geometry evaluate(Vec offset, Vec forward, const Rules& rules)
{
    Geometry g;
    if (!rules.valid()) return g;
    const double distance = std::hypot(offset.x, offset.y, offset.z);
    const double length = std::hypot(forward.x, forward.y, forward.z);
    if (!std::isfinite(distance) || !std::isfinite(length) || length < 1e-9 || distance < 1e-9) return g;
    const double cosine = (offset.x / distance) * (forward.x / length) +
        (offset.y / distance) * (forward.y / length) + (offset.z / distance) * (forward.z / length);
    g.known = true;
    g.distance = distance;
    g.angle_degrees = std::acos(std::clamp(cosine, -1.0, 1.0)) * 180.0 / pi;
    g.in_range = distance <= rules.range;
    g.in_front = g.angle_degrees <= rules.half_angle_degrees;
    return g;
}
enum class Attempt { unknown, cooling_down, outside_volume, eligible };
class Clock
{
    double mReadyAt = 0;
public:
    double remaining(double now) const { return std::max(0.0, mReadyAt - now); }
    void reset() { mReadyAt = 0; }
    Attempt attempt(double now, const Geometry& geometry, const Rules& rules)
    {
        if (!std::isfinite(now) || now < 0 || !rules.valid()) return Attempt::unknown;
        if (remaining(now) > 0) return Attempt::cooling_down; // Spam never extends the deadline.
        if (!rules.eligible_only || geometry.eligible()) mReadyAt = now + rules.cooldown;
        if (!geometry.known) return Attempt::unknown;
        return geometry.eligible() ? Attempt::eligible : Attempt::outside_volume;
    }
};
}
