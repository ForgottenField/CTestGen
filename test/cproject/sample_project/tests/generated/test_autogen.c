#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "utils.h"
#include "parser.h"

#define CHECK_EQ(actual, expected, name) do { if ((actual) != (expected)) { printf("FAIL:%s\n", (name)); return 1; } } while (0)

static int run_autogen_tests(void) {
    int tmp = 0;
    char key[32] = {0};
    char value[64] = {0};
    SensorRecord record = {0};
    SensorRecord record_low = { .id = 1, .reading = 10, .tag = "aa" };
    SensorRecord record_mid = { .id = 2, .reading = 30, .tag = "bb" };
    SensorRecord record_high = { .id = 3, .reading = 90, .tag = "cc" };
    SensorRecord out_records[4] = {0};
    size_t out_count = 0;
    const uint8_t ok_payload[] = {1,'i',1,'d',1,'=',1,'1',1,';',1,'r',1,'e',1,'a',1,'d',1,'i',1,'n',1,'g',1,'=',1,'2',1,'2',1,';',1,'t',1,'a',1,'g',1,'=',1,'o',1,'k'};
    const size_t ok_payload_len = sizeof(ok_payload);
    const uint8_t bad_payload[] = {0,'A'};
    const size_t bad_payload_len = sizeof(bad_payload);

    /* parse_sensor_line: normal line */
    CHECK_EQ(parse_sensor_line("id=1;reading=22;tag=ok", &record), 0, "parse_sensor_line:line_ok");
    /* parse_sensor_line: missing reading */
    CHECK_EQ(parse_sensor_line("id=1;tag=ok", &record), -7, "parse_sensor_line:line_missing_field");
    /* parse_sensor_line: unexpected key */
    CHECK_EQ(parse_sensor_line("id=1;reading=22;oops=1", &record), -6, "parse_sensor_line:line_bad_token");
    /* classify_record: low threshold */
    CHECK_EQ(classify_record(&record_low), 0, "classify_record:class_low");
    /* classify_record: high threshold */
    CHECK_EQ(classify_record(&record_high), 2, "classify_record:class_high");
    /* classify_record: mid-path parity */
    CHECK_EQ(classify_record(&record_mid), 1, "classify_record:class_mid_even_tag");
    /* parse_payload_packet: end-to-end parse */
    CHECK_EQ(parse_payload_packet(ok_payload, ok_payload_len, out_records, 4, &out_count), 0, "parse_payload_packet:packet_ok");
    /* parse_payload_packet: third-party decode failure path */
    CHECK_EQ(parse_payload_packet(bad_payload, bad_payload_len, out_records, 4, &out_count), -2, "parse_payload_packet:packet_decode_fail");
    /* clamp_int: lower bound */
    CHECK_EQ(clamp_int(-5, 0, 10), 0, "clamp_int:low_clamp");
    /* clamp_int: middle */
    CHECK_EQ(clamp_int(6, 0, 10), 6, "clamp_int:mid_value");
    /* clamp_int: upper bound */
    CHECK_EQ(clamp_int(30, 0, 10), 10, "clamp_int:high_clamp");
    /* parse_positive_int: valid digits */
    CHECK_EQ(parse_positive_int("123", &tmp), 0, "parse_positive_int:parse_ok");
    /* parse_positive_int: reject nondigit */
    CHECK_EQ(parse_positive_int("12a", &tmp), -2, "parse_positive_int:parse_bad_char");
    /* parse_positive_int: overflow guard */
    CHECK_EQ(parse_positive_int("9999999", &tmp), -3, "parse_positive_int:parse_overflow");
    /* split_kv: normal kv */
    CHECK_EQ(split_kv("id=12", key, sizeof(key), value, sizeof(value)), 0, "split_kv:kv_ok");
    /* split_kv: missing separator */
    CHECK_EQ(split_kv("id12", key, sizeof(key), value, sizeof(value)), -2, "split_kv:kv_missing_eq");
    /* split_kv: empty value */
    CHECK_EQ(split_kv("id=", key, sizeof(key), value, sizeof(value)), -2, "split_kv:kv_empty_value");
    return 0;
}

int main(void) {
    int rc = run_autogen_tests();
    if (rc == 0) {
        printf("ALL_TESTS_PASS\n");
    }
    return rc;
}
