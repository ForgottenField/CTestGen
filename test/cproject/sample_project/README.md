# Sample C Project Under Test

This project mimics a small telemetry parser with a third-party decompression dependency.

## Modules

- `src/utils.c`: primitive helpers and token parsing.
- `src/decoder.c`: frame decode interface.
- `src/third_party_adapter.c`: wrapper over vendor library.
- `vendor/miniz/src/miniz_stub.c`: simulated third-party RLE decompressor.
- `src/parser.c`: record parser and packet entry point.

## Intentional Bug

`parse_payload_packet` copies a line into a fixed 64-byte stack buffer without checking
whether the decoded line length fits, which can overflow when a long line is present.

