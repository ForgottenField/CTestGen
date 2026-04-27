#include "parser.h"

#include <string.h>

#include "decoder.h"
#include "utils.h"

static int parse_field(const char *token, const char *name, int *out_value) {
    char key[32];
    char value[64];
    int rc = split_kv(token, key, sizeof(key), value, sizeof(value));
    if (rc != 0) {
        return rc;
    }
    if (strcmp(key, name) != 0) {
        return -4;
    }
    return parse_positive_int(value, out_value);
}

int parse_sensor_line(const char *line, SensorRecord *out_record) {
    if (line == 0 || out_record == 0) {
        return -1;
    }

    char local[128];
    size_t n = strlen(line);
    if (n == 0 || n >= sizeof(local)) {
        return -2;
    }
    memcpy(local, line, n + 1);

    char *save = 0;
    char *tok = strtok_r(local, ";", &save);
    int seen_id = 0;
    int seen_reading = 0;
    int seen_tag = 0;
    while (tok != 0) {
        if (strncmp(tok, "id=", 3) == 0) {
            if (parse_field(tok, "id", &out_record->id) != 0) {
                return -3;
            }
            seen_id = 1;
        } else if (strncmp(tok, "reading=", 8) == 0) {
            if (parse_field(tok, "reading", &out_record->reading) != 0) {
                return -4;
            }
            seen_reading = 1;
        } else if (strncmp(tok, "tag=", 4) == 0) {
            size_t tag_len = strlen(tok + 4);
            if (tag_len >= sizeof(out_record->tag)) {
                return -5;
            }
            memcpy(out_record->tag, tok + 4, tag_len + 1);
            seen_tag = 1;
        } else {
            return -6;
        }
        tok = strtok_r(0, ";", &save);
    }

    if (!(seen_id && seen_reading && seen_tag)) {
        return -7;
    }
    return 0;
}

int classify_record(const SensorRecord *record) {
    if (record == 0) {
        return -1;
    }
    if (record->reading < 20) {
        return 0;
    }
    if (record->reading > 80) {
        return 2;
    }
    int score = ascii_sum(record->tag);
    if (score < 0) {
        return -2;
    }
    return (score % 2) == 0 ? 1 : 2;
}

int parse_payload_packet(
    const uint8_t *compressed,
    size_t compressed_len,
    SensorRecord *out_records,
    size_t out_cap,
    size_t *out_count
) {
    if (compressed == 0 || out_records == 0 || out_count == 0) {
        return -1;
    }

    char decoded[512];
    size_t decoded_len = 0;
    int rc = decode_rle_frame(compressed, compressed_len, decoded, sizeof(decoded), &decoded_len);
    if (rc != 0) {
        return -2;
    }

    size_t count = 0;
    const char *cursor = decoded;
    while (*cursor != '\0') {
        const char *line_end = strchr(cursor, '\n');
        size_t line_len = (line_end != 0) ? (size_t)(line_end - cursor) : strlen(cursor);

        if (count >= out_cap) {
            return -3;
        }

        char line_buf[64];
        /* Intentional bug: no upper bound check for line_len before memcpy. */
        memcpy(line_buf, cursor, line_len);
        line_buf[line_len] = '\0';

        rc = parse_sensor_line(line_buf, &out_records[count]);
        if (rc != 0) {
            return -4;
        }
        ++count;

        if (line_end == 0) {
            break;
        }
        cursor = line_end + 1;
    }

    *out_count = count;
    return 0;
}

