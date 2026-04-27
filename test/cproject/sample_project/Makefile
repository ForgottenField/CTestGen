CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -O0 -g

INCLUDES = -Iinclude -Ivendor/miniz/include
SRCS = src/utils.c src/decoder.c src/third_party_adapter.c src/parser.c vendor/miniz/src/miniz_stub.c

all: libsample.a

libsample.a: $(SRCS)
	$(CC) $(CFLAGS) $(INCLUDES) -c src/utils.c -o utils.o
	$(CC) $(CFLAGS) $(INCLUDES) -c src/decoder.c -o decoder.o
	$(CC) $(CFLAGS) $(INCLUDES) -c src/third_party_adapter.c -o third_party_adapter.o
	$(CC) $(CFLAGS) $(INCLUDES) -c src/parser.c -o parser.o
	$(CC) $(CFLAGS) $(INCLUDES) -c vendor/miniz/src/miniz_stub.c -o miniz_stub.o
	ar rcs libsample.a utils.o decoder.o third_party_adapter.o parser.o miniz_stub.o

clean:
	del /Q *.o libsample.a 2> NUL || exit 0

.PHONY: all clean

