#include <cstdint>
#include <cstddef>
#include "ecf_codec.h"
extern "C" {
size_t ecf_size(const std::uint8_t *in) { ECF::Decoder d; return d.getDecompressedSize(reinterpret_cast<const std::uint32_t *>(in)); }
size_t ecf_decode(const std::uint8_t *in, size_t nbytes, void *out) {
    ECF::Decoder d; return d(in, in + nbytes, reinterpret_cast<ECF::EventCD *>(out)); }
}
