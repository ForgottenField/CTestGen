#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* ---- project headers ---- */
#include "decoder.h"
#include "parser.h"
#include "utils.h"

/* ---- minimal test harness ---- */
static int g_pass = 0, g_fail = 0;

#define ASSERT_EQ(got, expected, id) do { \
    long long _g = (long long)(got); \
    long long _e = (long long)(expected); \
    if (_g == _e) { \
        g_pass++; \
    } else { \
        fprintf(stderr, "FAIL test %d: got %lld, expected %lld\n", (id), _g, _e); \
        g_fail++; \
    } \
} while(0)


static void test_decode_rle_frame(void) {
    /* 5 path(s) for decode_rle_frame */
    /* path 2: decode_rle_frame(NULL, 0, NULL, 0, NULL) -> -1 */
    ASSERT_EQ(decode_rle_frame(NULL, (size_t)0, NULL, (size_t)0, NULL), -1, 2);
    /* path 4: decode_rle_frame(NULL, 0, NULL, 0, &decoded_len) -> -1 */
    {
        size_t _local_decoded_len = {0};
        ASSERT_EQ(decode_rle_frame(NULL, (size_t)0, NULL, (size_t)0, &_local_decoded_len), -1, 4);
    }
    /* path 5: decode_rle_frame(NULL, 0, "", 0, NULL) -> -1 */
    ASSERT_EQ(decode_rle_frame(NULL, (size_t)0, "", (size_t)0, NULL), -1, 5);
    /* path 8: decode_rle_frame(NULL, 0, "", 0, &decoded_len) -> 0 */
    {
        size_t _local_decoded_len = {0};
        ASSERT_EQ(decode_rle_frame(NULL, (size_t)0, "", (size_t)0, &_local_decoded_len), 0, 8);
    }
    /* path 10: decode_rle_frame(NULL, 0, "", 18446744069414584319, &decoded_len) -> -2 */
    {
        size_t _local_decoded_len = {0};
        ASSERT_EQ(decode_rle_frame(NULL, (size_t)0, "", (size_t)18446744069414584319U, &_local_decoded_len), -2, 10);
    }
}

static void test_parse_sensor_line(void) {
    /* 8 path(s) for parse_sensor_line */
    /* path 41: parse_sensor_line(NULL, NULL) -> -1 */
    ASSERT_EQ(parse_sensor_line(NULL, NULL), -1, 41);
    /* path 47: parse_sensor_line("", &out_record) -> -2 */
    {
        SensorRecord _local_out_record = {0};
        ASSERT_EQ(parse_sensor_line("", &_local_out_record), -2, 47);
    }
    /* path 48: parse_sensor_line("", NULL) -> -1 */
    ASSERT_EQ(parse_sensor_line("", NULL), -1, 48);
    /* path 50: parse_sensor_line("A", &out_record) -> -7 */
    {
        SensorRecord _local_out_record = {0};
        ASSERT_EQ(parse_sensor_line("A", &_local_out_record), -7, 50);
    }
    /* path 69: parse_sensor_line("A", NULL) -> -7 */
    ASSERT_EQ(parse_sensor_line("A", NULL), -7, 69);
    /* path 88: parse_sensor_line("AA", &out_record) -> -7 */
    {
        SensorRecord _local_out_record = {0};
        ASSERT_EQ(parse_sensor_line("AA", &_local_out_record), -7, 88);
    }
    /* path 100: parse_sensor_line("AAA", &out_record) -> -7 */
    {
        SensorRecord _local_out_record = {0};
        ASSERT_EQ(parse_sensor_line("AAA", &_local_out_record), -7, 100);
    }
    /* path 114: parse_sensor_line("}", NULL) -> -7 */
    ASSERT_EQ(parse_sensor_line("}", NULL), -7, 114);
}

static void test_classify_record(void) {
    /* 2 path(s) for classify_record */
    /* path 42: classify_record(&record) -> 0 */
    {
        const SensorRecord _local_record = {0};
        ASSERT_EQ(classify_record(&_local_record), 0, 42);
    }
    /* path 44: classify_record(NULL) -> -1 */
    ASSERT_EQ(classify_record(NULL), -1, 44);
}

static void test_parse_payload_packet(void) {
    /* 11 path(s) for parse_payload_packet */
    /* path 43: parse_payload_packet(&compressed, 0, &out_records, 0, NULL) -> -1 */
    {
        const uint8_t _local_compressed = {0};
        SensorRecord _local_out_records = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, &_local_out_records, (size_t)0, NULL), -1, 43);
    }
    /* path 60: parse_payload_packet(&compressed, 0, &out_records, 0, &out_count) -> 0 */
    {
        const uint8_t _local_compressed = {0};
        SensorRecord _local_out_records = {0};
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, &_local_out_records, (size_t)0, &_local_out_count), 0, 60);
    }
    /* path 64: parse_payload_packet(&compressed, 0, &out_records, 18446744069414584319, &out_count) -> -4 */
    {
        const uint8_t _local_compressed = {0};
        SensorRecord _local_out_records = {0};
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, &_local_out_records, (size_t)18446744069414584319U, &_local_out_count), -4, 64);
    }
    /* path 78: parse_payload_packet(&compressed, 0, NULL, 0, NULL) -> -1 */
    {
        const uint8_t _local_compressed = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, NULL, (size_t)0, NULL), -1, 78);
    }
    /* path 93: parse_payload_packet(NULL, 0, NULL, 0, NULL) -> -1 */
    ASSERT_EQ(parse_payload_packet(NULL, (size_t)0, NULL, (size_t)0, NULL), -1, 93);
    /* path 106: parse_payload_packet(NULL, 0, NULL, 0, &out_count) -> -1 */
    {
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(NULL, (size_t)0, NULL, (size_t)0, &_local_out_count), -1, 106);
    }
    /* path 130: parse_payload_packet(&compressed, 0, NULL, 0, &out_count) -> -1 */
    {
        const uint8_t _local_compressed = {0};
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, NULL, (size_t)0, &_local_out_count), -1, 130);
    }
    /* path 166: parse_payload_packet(&compressed, 0, &out_records, 1, &out_count) -> -3 */
    {
        const uint8_t _local_compressed = {0};
        SensorRecord _local_out_records = {0};
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, &_local_out_records, (size_t)1U, &_local_out_count), -3, 166);
    }
    /* path 169: parse_payload_packet(&compressed, 0, &out_records, 18446744069414551551, &out_count) -> 0 */
    {
        const uint8_t _local_compressed = {0};
        SensorRecord _local_out_records = {0};
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, &_local_out_records, (size_t)18446744069414551551U, &_local_out_count), 0, 169);
    }
    /* path 230: parse_payload_packet(&compressed, 0, &out_records, 2, &out_count) -> -3 */
    {
        const uint8_t _local_compressed = {0};
        SensorRecord _local_out_records = {0};
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, &_local_out_records, (size_t)2U, &_local_out_count), -3, 230);
    }
    /* path 233: parse_payload_packet(&compressed, 0, &out_records, 3, &out_count) -> 0 */
    {
        const uint8_t _local_compressed = {0};
        SensorRecord _local_out_records = {0};
        size_t _local_out_count = {0};
        ASSERT_EQ(parse_payload_packet(&_local_compressed, (size_t)0, &_local_out_records, (size_t)3U, &_local_out_count), 0, 233);
    }
}

static void test_clamp_int(void) {
    /* 4 path(s) for clamp_int */
    /* path 3839: clamp_int(2147483648, 2147483648, 2147483630) */
    (void)clamp_int(2147483648, 2147483648, 2147483630); /* no return value captured */
    /* path 3848: clamp_int(2147483646, 2147483648, 2147483644) */
    (void)clamp_int(2147483646, 2147483648, 2147483644); /* no return value captured */
    /* path 3849: clamp_int(2147483646, 2147483647, 2147483647) */
    (void)clamp_int(2147483646, 2147483647, 2147483647); /* no return value captured */
    /* path 3850: clamp_int(0, 2147483649, 2147483648) */
    (void)clamp_int(0, 2147483649, 2147483648); /* no return value captured */
}

static void test_ascii_sum(void) {
    /* 5 path(s) for ascii_sum */
    /* path 3841: ascii_sum(NULL) -> -1 */
    ASSERT_EQ(ascii_sum(NULL), -1, 3841);
    /* path 3852: ascii_sum("") -> 0 */
    ASSERT_EQ(ascii_sum(""), 0, 3852);
    /* path 3853: ascii_sum("A") */
    (void)ascii_sum("A"); /* no return value captured */
    /* path 3866: ascii_sum("AA") */
    (void)ascii_sum("AA"); /* no return value captured */
    /* path 3870: ascii_sum("AAA") */
    (void)ascii_sum("AAA"); /* no return value captured */
}

static void test_parse_positive_int(void) {
    /* 15 path(s) for parse_positive_int */
    /* path 3843: parse_positive_int(NULL, NULL) -> -1 */
    ASSERT_EQ(parse_positive_int(NULL, NULL), -1, 3843);
    /* path 3855: parse_positive_int(NULL, &out_value) -> -1 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int(NULL, &_local_out_value), -1, 3855);
    }
    /* path 3864: parse_positive_int("", NULL) -> -1 */
    ASSERT_EQ(parse_positive_int("", NULL), -1, 3864);
    /* path 3876: parse_positive_int("A", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("A", &_local_out_value), -2, 3876);
    }
    /* path 3878: parse_positive_int("0", &out_value) -> 0 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("0", &_local_out_value), 0, 3878);
    }
    /* path 3882: parse_positive_int("0A", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("0A", &_local_out_value), -2, 3882);
    }
    /* path 3884: parse_positive_int("0:", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("0:", &_local_out_value), -2, 3884);
    }
    /* path 3885: parse_positive_int("00", &out_value) -> 0 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("00", &_local_out_value), 0, 3885);
    }
    /* path 3889: parse_positive_int("000", &out_value) -> 0 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("000", &_local_out_value), 0, 3889);
    }
    /* path 3893: parse_positive_int("p", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("p", &_local_out_value), -2, 3893);
    }
    /* path 3894: parse_positive_int("", &out_value) -> -1 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("", &_local_out_value), -1, 3894);
    }
    /* path 3896: parse_positive_int("00A", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("00A", &_local_out_value), -2, 3896);
    }
    /* path 3902: parse_positive_int("00<", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("00<", &_local_out_value), -2, 3902);
    }
    /* path 3909: parse_positive_int("000A", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("000A", &_local_out_value), -2, 3909);
    }
    /* path 3918: parse_positive_int("000@", &out_value) -> -2 */
    {
        int _local_out_value = {0};
        ASSERT_EQ(parse_positive_int("000@", &_local_out_value), -2, 3918);
    }
    /* [llm] parse_positive_int("1000001", &out_value) -> -3 */
    {
        int _probe_out_value = {0};
        ASSERT_EQ(parse_positive_int("1000001", &_probe_out_value), -3, 90000);
    }
}

static void test_split_kv(void) {
    /* 15 path(s) for split_kv */
    /* path 3847: split_kv(NULL, NULL, 0, NULL, 0) -> -1 */
    ASSERT_EQ(split_kv(NULL, NULL, (size_t)0, NULL, (size_t)0), -1, 3847);
    /* path 3859: split_kv(NULL, NULL, 0, "", 0) -> -1 */
    ASSERT_EQ(split_kv(NULL, NULL, (size_t)0, "", (size_t)0), -1, 3859);
    /* path 3900: split_kv(NULL, "", 0, NULL, 0) -> -1 */
    ASSERT_EQ(split_kv(NULL, "", (size_t)0, NULL, (size_t)0), -1, 3900);
    /* path 3907: split_kv(NULL, "", 0, "", 0) -> -1 */
    ASSERT_EQ(split_kv(NULL, "", (size_t)0, "", (size_t)0), -1, 3907);
    /* path 3934: split_kv("", NULL, 0, NULL, 0) -> -1 */
    ASSERT_EQ(split_kv("", NULL, (size_t)0, NULL, (size_t)0), -1, 3934);
    /* path 3940: split_kv("", NULL, 0, "", 0) -> -1 */
    ASSERT_EQ(split_kv("", NULL, (size_t)0, "", (size_t)0), -1, 3940);
    /* path 3941: split_kv("", "", 0, NULL, 0) -> -1 */
    ASSERT_EQ(split_kv("", "", (size_t)0, NULL, (size_t)0), -1, 3941);
    /* path 3948: split_kv("AA", "AA", 9223372032559808512, "AA", 18446741870391328766) -> 0 */
    ASSERT_EQ(split_kv("AA", "AA", (size_t)9223372032559808512U, "AA", (size_t)18446741870391328766U), 0, 3948);
    /* path 3949: split_kv("AA", "AA", 9223372032559808512, "AA", 18446744069414584319) -> -3 */
    ASSERT_EQ(split_kv("AA", "AA", (size_t)9223372032559808512U, "AA", (size_t)18446744069414584319U), -3, 3949);
    /* path 3950: split_kv("A", "A", 18446744069414584319, "A", 18446744069414584319) -> -2 */
    ASSERT_EQ(split_kv("A", "A", (size_t)18446744069414584319U, "A", (size_t)18446744069414584319U), -2, 3950);
    /* path 3953: split_kv("", "", 18446744069414584319, "", 18446744069414584319) -> -2 */
    ASSERT_EQ(split_kv("", "", (size_t)18446744069414584319U, "", (size_t)18446744069414584319U), -2, 3953);
    /* path 3954: split_kv("@A", "@A", 1, "@A", 18446744069414584319) -> -3 */
    ASSERT_EQ(split_kv("@A", "@A", (size_t)1U, "@A", (size_t)18446744069414584319U), -3, 3954);
    /* path 3955: split_kv("=", "=", 18446744069414584319, "=", 18446744069414584319) -> -2 */
    ASSERT_EQ(split_kv("=", "=", (size_t)18446744069414584319U, "=", (size_t)18446744069414584319U), -2, 3955);
    /* path 3956: split_kv("", "", 18446744069414584319, "", 0) -> -1 */
    ASSERT_EQ(split_kv("", "", (size_t)18446744069414584319U, "", (size_t)0), -1, 3956);
    /* path 3957: split_kv("", "", 0, "", 0) -> -1 */
    ASSERT_EQ(split_kv("", "", (size_t)0, "", (size_t)0), -1, 3957);
}

int main(void) {
    test_decode_rle_frame();
    test_parse_sensor_line();
    test_classify_record();
    test_parse_payload_packet();
    test_clamp_int();
    test_ascii_sum();
    test_parse_positive_int();
    test_split_kv();
    printf("Results: %d passed, %d failed\n", g_pass, g_fail);
    return g_fail > 0 ? 1 : 0;
}
