// SPDX-License-Identifier: MIT
#pragma once

// Picks use a signed -1 sentinel; texture accessors accept U8. Validate before
// that conversion, including when a confirmation resumes after a shape change.
template<class Object>
bool fsmcpValidDropFace(Object* object, int face)
{
    return object && !object->isDead() && face >= 0 &&
        face < object->getNumTEs() && object->getTE(static_cast<unsigned char>(face)) != nullptr;
}

template<class Object>
bool fsmcpValidDropSurface(Object* object, int face, bool all_faces)
{
    if (!object || object->isDead() || object->getNumTEs() == 0)
        return false;
    // Shift deliberately ignores the picked face, including the -1 sentinel.
    return all_faces || fsmcpValidDropFace(object, face);
}
