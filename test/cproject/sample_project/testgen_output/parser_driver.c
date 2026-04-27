#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>
#include <ctype.h>

#include "/home/yanghq/csa-testgen/stubs/lib_stubs.h"

#include "/home/yanghq/csa-testgen/test/cproject/sample_project/src/parser.c"

static void driver_parse_sensor_line(void) {
    char line_buf[256] = {0};
    SensorRecord *out_record = (SensorRecord *)calloc(1, sizeof(SensorRecord));
    scanf("%255s", line_buf);
    char *line = (char *)malloc(strlen(line_buf) + 1);
    if (line) strcpy(line, line_buf);
    int _r = parse_sensor_line(line, out_record);
    (void)_r;
    free(line);
    free(out_record);
}

static void driver_classify_record(void) {
    SensorRecord *record = (SensorRecord *)calloc(1, sizeof(SensorRecord));
    int _r = classify_record(record);
    (void)_r;
    free(record);
}

static void driver_parse_payload_packet(void) {
    uint8_t *compressed = (uint8_t *)calloc(1, sizeof(uint8_t));
    size_t compressed_len;
    SensorRecord *out_records = (SensorRecord *)calloc(1, sizeof(SensorRecord));
    size_t out_cap;
    size_t out_count_val;
    scanf("%zu %zu %zu", &compressed_len, &out_cap, &out_count_val);
    size_t *out_count = (size_t *)malloc(sizeof(size_t));
    if (out_count) *out_count = out_count_val;
    int _r = parse_payload_packet(compressed, compressed_len, out_records, out_cap, out_count);
    (void)_r;
    free(compressed);
    free(out_records);
    free(out_count);
}

int main(void) {
    driver_parse_sensor_line();
    driver_classify_record();
    driver_parse_payload_packet();
    return 0;
}
