// SPDX-License-Identifier: MIT
#include "../viewer-extension/fsmcpdropguard.h"
#include <cassert>
#include <climits>
#include <iostream>

struct Object
{
    int count = 8;
    bool dead = false;
    bool missing = false;
    int reads = 0;
    bool isDead() { return dead; }
    int getNumTEs() { return count; }
    Object* getTE(unsigned char face)
    {
        // Model the viewer's narrowing boundary; invalid access must not occur.
        assert(face < count);
        ++reads;
        return missing ? nullptr : this;
    }
};

int main()
{
    Object object;
    for (int face : {-1, -2, 8, 255, 256, INT_MIN, INT_MAX})
    {
        assert(!fsmcpValidDropFace(&object, face));
        assert(!fsmcpValidDropSurface(&object, face, false));
    }
    assert(object.reads == 0);
    assert(fsmcpValidDropFace(&object, 0));
    assert(fsmcpValidDropFace(&object, 7));
    object.reads = 0;
    assert(fsmcpValidDropSurface(&object, -1, true));
    assert(object.reads == 0);
    object.count = 2; // confirmation resumes after a shape change
    assert(!fsmcpValidDropSurface(&object, 7, false));
    object.missing = true;
    assert(!fsmcpValidDropFace(&object, 0));
    object.count = 0;
    assert(!fsmcpValidDropSurface(&object, -1, true));
    object.count = 8;
    object.dead = true;
    assert(!fsmcpValidDropSurface(&object, -1, true));
    assert(!fsmcpValidDropFace(&object, 0));
    assert(!fsmcpValidDropSurface<Object>(nullptr, -1, true));
    assert(!fsmcpValidDropFace<Object>(nullptr, 0));
    std::cout << "Native signed-face drop regression passed; no viewer contacted.\n";
}
