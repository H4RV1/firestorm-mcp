// SPDX-License-Identifier: MIT
#pragma once
#include <algorithm>
#include <cstring>
#include <cstdint>
#include <string>
#include <vorbis/vorbisfile.h>
namespace fsmcp {
constexpr size_t MAX_AUDIO = 8 * 1024 * 1024;
// No viewer state is read by these callbacks or the validation worker.
struct MemoryOgg { const std::string& data; size_t offset = 0; };
size_t oggRead(void* out, size_t size, size_t count, void* source) {
    auto& m = *static_cast<MemoryOgg*>(source);
    if (!size) return 0;
    size_t n = std::min(count, (m.data.size() - m.offset) / size);
    memcpy(out, m.data.data() + m.offset, n * size); m.offset += n * size; return n;
}
int oggSeek(void* source, ogg_int64_t offset, int origin) {
    auto& m = *static_cast<MemoryOgg*>(source);
    ogg_int64_t pos = offset + (origin == SEEK_CUR ? m.offset : origin == SEEK_END ? m.data.size() : 0);
    if (pos < 0 || pos > (ogg_int64_t)m.data.size()) return -1;
    m.offset = (size_t)pos; return 0;
}
long oggTell(void* source) { return (long)static_cast<MemoryOgg*>(source)->offset; }
inline uint32_t u32(const std::string& s, size_t i) {
    return uint32_t((uint8_t)s[i]) | uint32_t((uint8_t)s[i+1]) << 8 |
        uint32_t((uint8_t)s[i+2]) << 16 | uint32_t((uint8_t)s[i+3]) << 24;
}
inline bool validFraming(const std::string& data) {
    if (data.empty() || data.size() > MAX_AUDIO) return false;
    size_t offset = 0; uint32_t serial = 0, sequence = 0; bool ended = false, continued = false;
    while (offset < data.size()) {
        if (ended || data.size() - offset < 27 || data.compare(offset, 5, std::string("OggS\0", 5))) return false;
        unsigned flags = (uint8_t)data[offset+5], count = (uint8_t)data[offset+26];
        if ((flags & ~7) || bool(flags & 1) != continued || offset + 27 + count > data.size()) return false;
        if (sequence == 0) { if (flags != 2) return false; serial = u32(data, offset+14); }
        else if (flags & 2) return false;
        if (u32(data, offset+14) != serial || u32(data, offset+18) != sequence) return false;
        size_t end = offset + 27 + count;
        for (unsigned i = 0; i < count; ++i) end += (uint8_t)data[offset+27+i];
        if (end > data.size()) return false;
        uint32_t crc = 0;
        for (size_t i = offset; i < end; ++i) {
            crc ^= uint32_t(i >= offset+22 && i < offset+26 ? 0 : (uint8_t)data[i]) << 24;
            for (int bit = 0; bit < 8; ++bit) crc = (crc << 1) ^ ((crc & 0x80000000) ? 0x04c11db7 : 0);
        }
        if (crc != u32(data, offset+22)) return false;
        if (count) continued = (uint8_t)data[offset+26+count] == 255;
        if (flags & 4) {
            ended = true; uint64_t granule = u32(data, offset+6) | uint64_t(u32(data, offset+10)) << 32;
            if (continued || !granule || granule > 30 * 44100) return false;
        }
        offset = end; ++sequence;
    }
    return ended;
}
inline bool validateSound(const std::string& data) {
    if (!validFraming(data)) return false;
    if (data.empty() || data.size() > MAX_AUDIO) return false;
    MemoryOgg memory{data}; OggVorbis_File vf{};
    if (ov_open_callbacks(&memory, &vf, nullptr, 0, {oggRead, oggSeek, nullptr, oggTell}) < 0) return false;
    auto* info = ov_info(&vf, -1);
    bool valid = ov_streams(&vf) == 1 && info && info->channels == 1 && info->rate == 44100;
    ogg_int64_t total = ov_pcm_total(&vf, -1), decoded = 0;
    valid = valid && total > 0 && total <= 30 * 44100;
    char pcm[8192]; int stream = 0; long n = 0;
    while (valid && (n = ov_read(&vf, pcm, sizeof(pcm), 0, 2, 1, &stream)) != 0) {
        if (n < 0 || stream != 0) { valid = false; break; }
        decoded += n / 2;
        if (decoded > 30 * 44100) valid = false;
    }
    ov_clear(&vf); return valid && decoded == total;
}

} // namespace fsmcp
