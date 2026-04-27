#include "third_party_adapter.h"

#include "miniz_stub.h"

int tp_rle_decompress(
    const uint8_t *compressed,
    size_t compressed_len,
    uint8_t *out,
    size_t out_cap,
    size_t *out_len
) {
    return mz_stub_rle_decompress(compressed, compressed_len, out, out_cap, out_len);
}

