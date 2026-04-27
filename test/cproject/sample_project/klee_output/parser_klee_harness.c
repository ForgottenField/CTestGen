/* KLEE harness — auto-generated from parser.c */
#include "/home/yanghq/klee/klee/include/klee/klee.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>

/* Project headers */
#include "/home/yanghq/csa-testgen/test/cproject/sample_project/include/parser.h"
#include "/home/yanghq/csa-testgen/test/cproject/sample_project/include/decoder.h"
#include "/home/yanghq/csa-testgen/test/cproject/sample_project/include/utils.h"

static void klee_test_parse_sensor_line(void) {
    char _buf_line[64];
    klee_make_symbolic(_buf_line, sizeof(_buf_line), "line");
    klee_assume(_buf_line[63] == '\0');
    const char *line = _buf_line;
    SensorRecord _obj_out_record;
    memset(&_obj_out_record, 0, sizeof(_obj_out_record));
    SensorRecord* out_record = &_obj_out_record;
    int _r = parse_sensor_line(line, out_record);
    (void)_r;
}

static void klee_test_classify_record(void) {
    SensorRecord _obj_record;
    memset(&_obj_record, 0, sizeof(_obj_record));
    const SensorRecord* record = &_obj_record;
    int _r = classify_record(record);
    (void)_r;
}

static void klee_test_parse_payload_packet(void) {
    uint8_t _obj_compressed;
    memset(&_obj_compressed, 0, sizeof(_obj_compressed));
    const uint8_t* compressed = &_obj_compressed;
    size_t compressed_len;
    klee_make_symbolic(&compressed_len, sizeof(compressed_len), "compressed_len");
    SensorRecord _obj_out_records;
    memset(&_obj_out_records, 0, sizeof(_obj_out_records));
    SensorRecord* out_records = &_obj_out_records;
    size_t out_cap;
    klee_make_symbolic(&out_cap, sizeof(out_cap), "out_cap");
    size_t _local_out_count = 0;
    size_t* out_count = &_local_out_count;
    int _r = parse_payload_packet(compressed, compressed_len, out_records, out_cap, out_count);
    (void)_r;
}

int main(void) {
    unsigned klee_choice;
    klee_make_symbolic(&klee_choice, sizeof(klee_choice), "choice");
    klee_assume(klee_choice < 3u);
    switch (klee_choice) {
        case 0: klee_test_parse_sensor_line(); break;
        case 1: klee_test_classify_record(); break;
        case 2: klee_test_parse_payload_packet(); break;
        default: break;
    }
    return 0;
}
