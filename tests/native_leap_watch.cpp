// SPDX-License-Identifier: MIT
#include <cassert>
#include <memory>
#include <string>
#include <vector>
#include <sstream>
#include <iostream>
using U32 = unsigned int;
std::ostringstream sink;
#define LL_WARNS(tag) sink
#define LL_INFOS(tag) sink
#define LL_ENDL std::endl
struct LLEventTimer {
    float period;
    explicit LLEventTimer(float value): period(value) {}
    virtual ~LLEventTimer() = default;
    virtual bool tick() = 0;
};
bool exiting = false, fail_launch = false;
struct LLApp { static bool isExiting() { return exiting; } };
struct LLLeap {
    using weak_t = std::weak_ptr<LLLeap>;
    weak_t self;
    weak_t getWeak() { return self; }
    static LLLeap* create(const std::string&, const std::string&, bool);
};
std::vector<std::shared_ptr<LLLeap>> children;
int launches = 0;
LLLeap* LLLeap::create(const std::string&, const std::string& command, bool) {
    assert(command == "synthetic configured helper");
    ++launches;
    if (fail_launch) return nullptr;
    auto child = std::make_shared<LLLeap>();
    child->self = child; children.push_back(child);
    return child.get();
}

// GENERATED_WATCH

int main() {
    auto initial = LLLeap::create("", "synthetic configured helper", false);
    MCPLeapWatch watch("synthetic configured helper", initial);
    assert(watch.period == 2.f);
    for (int i=0; i<1000; ++i) assert(!watch.tick());
    assert(launches == 1); // no duplicate helper while the owner is alive
    children.back().reset();
    assert(!watch.tick() && launches == 2);
    children.back().reset();
    assert(!watch.tick() && launches == 2);
    assert(!watch.tick() && launches == 3);
    children.back().reset();
    for (int i=0; i<3; ++i) assert(!watch.tick() && launches == 3);
    assert(!watch.tick() && launches == 4);
    // The third restarted child may remain healthy indefinitely.
    for (int i=0; i<1000; ++i) assert(!watch.tick());
    children.back().reset();
    assert(watch.tick() && launches == 4); // hard lifetime budget
    fail_launch = true;
    MCPLeapWatch failing("synthetic configured helper", nullptr);
    for (int i=0; i<7; ++i) assert(!failing.tick());
    assert(launches == 7 && failing.tick());
    MCPLeapWatch shutdown("synthetic configured helper", nullptr);
    exiting = true;
    assert(shutdown.tick() && launches == 7);
    std::cout << "Actual helper watcher passed lifetime, backoff, limit and shutdown regressions.\n";
}
