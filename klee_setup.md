# KLEE 环境配置文档

## 概述

本项目使用 KLEE 3.3-pre（动态符号执行工具）作为 CSA 测试生成工具的覆盖率基线对比。KLEE 需要与对应版本的 LLVM 匹配构建，并配备 klee-uclibc 以支持 C 标准库函数的符号执行。

---

## 当前安装路径

| 组件 | 路径 |
|------|------|
| KLEE 源码 | `/home/yanghq/klee/klee/` |
| KLEE 构建（LLVM 18） | `/home/yanghq/klee/build-llvm18/` |
| klee-uclibc | `/home/yanghq/klee/klee-uclibc/` |
| `klee` 主程序 | `/home/yanghq/klee/build-llvm18/bin/klee` |
| `klee-replay` | `/home/yanghq/klee/build-llvm18/bin/klee-replay` |
| `ktest-tool` | `/home/yanghq/klee/build-llvm18/bin/ktest-tool` |
| `libkleeRuntest.so` | `/home/yanghq/klee/build-llvm18/lib/libkleeRuntest.so` |
| `klee.h` | `/home/yanghq/klee/klee/include/klee/klee.h` |
| bitcode 编译器 | `/home/yanghq/llvm/llvm-project/build/bin/clang`（本地 LLVM 18.1.3） |

---

## 关键说明：LLVM 版本兼容性

本机同时存在三个 LLVM 18 相关安装：

| 安装 | 路径 | 用途 |
|------|------|------|
| 系统 LLVM 18.1.3 | `/usr/lib/llvm-18/` | KLEE 主程序链接目标 |
| 本地构建 LLVM 18.1.3 | `/home/yanghq/llvm/llvm-project/build/` | CSA 分析 + bitcode 编译 |
| 旧版 KLEE（LLVM 14） | `/home/yanghq/klee/klee/build/` | **已废弃，不使用** |

**重要**：KLEE 主程序链接系统 LLVM 18（`/usr/lib/llvm-18`），但 runtime bitcode 编译使用本地 clang-18（`/home/yanghq/llvm/llvm-project/build/bin/clang`）。直接使用系统 clang-18 会因 LLVM 双重加载导致 `CommandLine Error: Option ... registered more than once` 错误。

---

## 从零安装步骤（如需在新机器复现）

### 前置条件

```bash
# Ubuntu 22.04/24.04
sudo apt-get install -y cmake ninja-build python3-pip git
sudo apt-get install -y libz3-dev z3
sudo apt-get install -y llvm-18 clang-18  # 系统 LLVM 18
# 确保本地 LLVM 18 已编译（项目通用步骤，此处假设已完成）
```

### Step 1：克隆并构建 klee-uclibc

klee-uclibc 是 uClibc 的 KLEE 专用版本，编译为 LLVM bitcode 供符号执行使用。

```bash
cd /home/yanghq/klee
git clone https://github.com/klee/klee-uclibc.git klee-uclibc
cd klee-uclibc

# 使用系统 clang-18 配置（需要 clean PATH 避免 LLVM 双重加载）
env -i HOME=/home/yanghq PATH=/usr/lib/llvm-18/bin:/usr/bin:/bin \
./configure \
    --make-llvm-lib \
    --with-cc=/usr/lib/llvm-18/bin/clang \
    --with-llvm-config=/usr/bin/llvm-config-18

# 构建（同样使用 clean 环境）
env -i HOME=/home/yanghq PATH=/usr/lib/llvm-18/bin:/usr/bin:/bin \
make -j$(nproc)

# 验证
ls lib/libc.a  # 应存在此文件
```

### Step 2：构建 KLEE（LLVM 18 + klee-uclibc）

```bash
mkdir -p /home/yanghq/klee/build-llvm18
cd /home/yanghq/klee/build-llvm18

cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DLLVM_DIR=/usr/lib/llvm-18/lib/cmake/llvm \
    -DLLVMCC=/home/yanghq/llvm/llvm-project/build/bin/clang \
    -DLLVMCXX=/home/yanghq/llvm/llvm-project/build/bin/clang++ \
    -DENABLE_SOLVER_Z3=ON \
    -DKLEE_UCLIBC_PATH=/home/yanghq/klee/klee-uclibc \
    -DENABLE_POSIX_RUNTIME=ON \
    -DENABLE_UNIT_TESTS=OFF \
    -DENABLE_SYSTEM_TESTS=OFF \
    ../klee

ninja -j$(nproc)
```

**CMake 选项说明**：

| 选项 | 值 | 说明 |
|------|----|------|
| `LLVM_DIR` | `/usr/lib/llvm-18/lib/cmake/llvm` | 系统 LLVM 18 — klee 主程序链接库 |
| `LLVMCC` | 本地 clang-18 | 用于编译 KLEE runtime bitcode（避免重复注册错误） |
| `KLEE_UCLIBC_PATH` | `/home/yanghq/klee/klee-uclibc` | C 库符号执行支持 |
| `ENABLE_POSIX_RUNTIME` | ON | 启用 POSIX 环境模拟 |
| `ENABLE_UNIT_TESTS=OFF` | — | 跳过需要 lit 工具的测试 |

### Step 3：验证安装

```bash
/home/yanghq/klee/build-llvm18/bin/klee --version
# 期望输出：KLEE 3.3-pre ... Ubuntu LLVM version 18.1.3

# 运行简单测试
cat > /tmp/test_klee.c << 'EOF'
#include <klee/klee.h>
int main(void) {
    int x;
    klee_make_symbolic(&x, sizeof(x), "x");
    if (x > 0) return 1;
    return 0;
}
EOF
/home/yanghq/llvm/llvm-project/build/bin/clang \
    -I/home/yanghq/klee/klee/include \
    -g -O0 -emit-llvm -c /tmp/test_klee.c -o /tmp/test_klee.bc
/home/yanghq/klee/build-llvm18/bin/klee \
    --libc=uclibc --posix-runtime \
    --output-dir=/tmp/klee_test_out \
    /tmp/test_klee.bc
ls /tmp/klee_test_out/*.ktest  # 应有2个（x>0 和 x<=0 两条路径）
```

---

## 使用 run_klee_testgen.sh

```bash
cd /home/yanghq/csa-testgen
chmod +x run_klee_testgen.sh

# 对 sample_project 运行 KLEE 测试生成
./run_klee_testgen.sh test/cproject/sample_project/

# 指定自定义输出目录
./run_klee_testgen.sh test/cproject/sample_project/ /tmp/klee_output/

# 调整每个 harness 的 KLEE 执行时间（默认 120s）
KLEE_MAX_TIME=60s ./run_klee_testgen.sh test/cproject/sample_project/
```

输出目录结构：
```
klee_output/
├── utils_klee_harness.c          # 生成的 KLEE harness
├── utils_src.bc                   # 源文件 bitcode
├── utils_harness.bc               # harness bitcode
├── utils_linked.bc                # 链接后的 bitcode
├── klee_out_utils/                # KLEE 输出目录
│   ├── test000001.ktest           # 测试用例（具体输入值）
│   ├── test000002.ktest
│   ├── ...
│   ├── run.stats                  # KLEE 统计
│   └── messages.txt               # KLEE 日志
├── parser_klee_harness.c
├── klee_out_parser/
│   └── ...
└── cov_work/                      # gcov 覆盖率工作目录
    ├── utils_cov                  # coverage-instrumented binary
    └── ...
```

---

## 常见问题

### `CommandLine Error: Option ... registered more than once`

**原因**：系统 clang-18 与本地 LLVM 18 共存，运行时双重加载。

**解决**：
1. 使用 `env -i` 净化环境（构建 klee-uclibc 时）
2. cmake 中 `LLVMCC` 使用本地 clang（`/home/yanghq/llvm/llvm-project/build/bin/clang`），而非系统 clang-18

### klee 二进制缺失（only libkleeRuntest.so 生成）

**原因**：cmake 使用了本地 LLVM 构建目录作为 `LLVM_DIR`，但本地构建缺少 `libLLVMMCJIT.a`。

**解决**：将 `LLVM_DIR` 改为系统 LLVM 18 的 cmake 配置（`/usr/lib/llvm-18/lib/cmake/llvm`）。

### klee-uclibc configure 找不到 llvm-config

**原因**：本地 LLVM 构建未生成 `llvm-config` 二进制。

**解决**：使用系统 `llvm-config-18`（`/usr/bin/llvm-config-18`）。

### KLEE 运行时 `--libc=uclibc: not found`

**原因**：KLEE 未找到 uclibc runtime bitcode。

**解决**：确认 `KLEE_UCLIBC_PATH` 在 cmake 构建时正确指向 klee-uclibc 目录，且 `lib/libc.a` 存在。

### KLEE 启动即崩溃：`Instrument.cpp:18: assert(0)`

**原因**：KLEE 3.3-pre 对 LLVM ≥ 17 使用 `Instrument.cpp` 和 `Optimize.cpp`，但这两个文件仅含 `assert(0)` 占位实现，真正的实现在 `InstrumentLegacy.cpp` 中。

**解决**：已修改 `klee/lib/Module/Instrument.cpp` 和 `Optimize.cpp`，将占位实现替换为基于 legacy pass manager 的真实实现（从 `InstrumentLegacy.cpp` 复制）。注意：`createScalarizerPass()` 在 LLVM 17+ 中已删除，已跳过此 pass（影响极小）。

### `klee-replay` 不设置 `KTEST_FILE`：`KLEE-RUNTIME: KTEST_FILE not set`

**原因**：KLEE 3.3-pre 的 `klee-replay` 不再自动将 `KTEST_FILE` 设置为环境变量，而是直接 `execv` 执行二进制。但 `libkleeRuntest.so` 的 `klee_make_symbolic()` 仍需从 `KTEST_FILE` 读取 ktest 文件。

**解决**：不使用 `klee-replay`，改用直接设置 `KTEST_FILE` 环境变量运行覆盖率二进制：
```bash
KTEST_FILE="path/to/test.ktest" LD_LIBRARY_PATH="$KLEE_LIB" ./cov_binary
```

### `ls *.ktest: Argument list too long`

**原因**：KLEE 对某些函数生成大量（10万+）ktest 文件，shell glob 展开失败。

**解决**：使用 `find "$KLEE_OUT" -name "*.ktest" | wc -l` 代替 `ls *.ktest | wc -l`；回放时用 `find ... | head -500` 限制数量。

---

## 版本信息

- KLEE: 3.3-pre (commit 769342c6)
- LLVM: 18.1.3
- klee-uclibc: latest main branch
- 构建日期: 2026-04-22
