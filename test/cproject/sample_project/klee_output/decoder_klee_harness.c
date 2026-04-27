/* KLEE harness — auto-generated from decoder.c */
#include "/home/yanghq/klee/klee/include/klee/klee.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>

/* Project headers */
#include "/home/yanghq/csa-testgen/test/cproject/sample_project/include/decoder.h"
#include "/home/yanghq/csa-testgen/test/cproject/sample_project/include/third_party_adapter.h"

static void klee_test_decode_rle_frame(void) {
    uint8_t _obj_compressed;
    memset(&_obj_compressed, 0, sizeof(_obj_compressed));
    const uint8_t* compressed = &_obj_compressed;
    size_t compressed_len;
    klee_make_symbolic(&compressed_len, sizeof(compressed_len), "compressed_len");
    char _buf_decoded_text[64];
    memset(_buf_decoded_text, 0, sizeof(_buf_decoded_text));
    char *decoded_text = _buf_decoded_text;
    size_t decoded_cap;
    klee_make_symbolic(&decoded_cap, sizeof(decoded_cap), "decoded_cap");
    size_t _local_decoded_len = 0;
    size_t* decoded_len = &_local_decoded_len;
    int _r = decode_rle_frame(compressed, compressed_len, decoded_text, decoded_cap, decoded_len);
    (void)_r;
}

int main(void) {
    unsigned klee_choice;
    klee_make_symbolic(&klee_choice, sizeof(klee_choice), "choice");
    klee_assume(klee_choice < 1u);
    switch (klee_choice) {
        case 0: klee_test_decode_rle_frame(); break;
        default: break;
    }
    return 0;
}
