#ifndef PARSER_H
#define PARSER_H

#include <stddef.h>
#include <stdint.h>

typedef struct SensorRecord {
    int id;
    int reading;
    char tag[32];
} SensorRecord;

int parse_sensor_line(const char *line, SensorRecord *out_record);
int classify_record(const SensorRecord *record);
int parse_payload_packet(
    const uint8_t *compressed,
    size_t compressed_len,
    SensorRecord *out_records,
    size_t out_cap,
    size_t *out_count
);

#endif

