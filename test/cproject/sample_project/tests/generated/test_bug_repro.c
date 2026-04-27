#include <stddef.h>
#include <stdint.h>
#include "parser.h"

/* Generated bug repro test input; run under ASan/UBSan for overflow detection. */
int main(void) {
    static const uint8_t compressed[] = {
        1, 105, 1, 100, 1, 61, 1, 49, 1, 59, 1, 114, 1, 101, 1, 97, 1, 100, 1, 105, 1, 110, 1, 103, 1, 61, 2, 57, 1, 59, 1, 116, 1, 97, 1, 103, 1, 61, 76, 65, 1, 10
    };
    SensorRecord out_records[2] = {0};
    size_t out_count = 0;
    return parse_payload_packet(compressed, sizeof(compressed), out_records, 2, &out_count);
}
