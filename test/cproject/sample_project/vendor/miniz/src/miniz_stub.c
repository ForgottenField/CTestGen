#include "miniz_stub.h"

int mz_stub_rle_decompress(
    const uint8_t *compressed,
    size_t compressed_len,
    uint8_t *out,
    size_t out_cap,
    size_t *out_len
) {
    if (compressed == 0 || out == 0 || out_len == 0) {
        return MZ_STUB_BAD_INPUT;
    }
    if (compressed_len == 0 || (compressed_len % 2) != 0) {
        return MZ_STUB_BAD_INPUT;
    }

    size_t written = 0;
    for (size_t i = 0; i < compressed_len; i += 2) {
        uint8_t count = compressed[i];
        uint8_t byte = compressed[i + 1];
        if (count == 0) {
            return MZ_STUB_BAD_INPUT;
        }
        if (written + count > out_cap) {
            return MZ_STUB_NO_SPACE;
        }
        for (uint8_t j = 0; j < count; ++j) {
            out[written++] = byte;
        }
    }

    *out_len = written;
    return MZ_STUB_OK;
}

