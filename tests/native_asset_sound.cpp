// SPDX-License-Identifier: MIT
#include "../viewer-extension/fsmcpsound.h"
#include <fstream>
#include <cassert>
#include <iostream>
int main(int argc, char** argv) {
    assert(argc == 4); // synthetic mono, stereo, wrong-rate Vorbis fixtures
    auto read = [](const char* path) { std::ifstream in(path, std::ios::binary); return std::string(std::istreambuf_iterator<char>(in), {}); };
    auto valid = read(argv[1]);
    assert(fsmcp::validateSound(valid));
    assert(!fsmcp::validateSound(read(argv[2])));
    assert(!fsmcp::validateSound(read(argv[3])));
    assert(!fsmcp::validateSound(""));
    assert(!fsmcp::validateSound(std::string(8*1024*1024+1, 'x')));
    assert(!fsmcp::validateSound(valid + "trailing garbage"));
    assert(!fsmcp::validateSound(valid + valid));
    assert(!fsmcp::validateSound(valid.substr(0, valid.size()-1)));
    valid[valid.size()/2] ^= 1;
    assert(!fsmcp::validateSound(valid));
    std::cout << "9 native codec assertions passed (synthetic assets; no upload)\n";
}
