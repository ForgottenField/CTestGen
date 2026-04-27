# CSA Test Generation Tool

基于 Clang Static Analyzer (CSA) 的自动化测试用例生成工具，通过符号执行提取路径约束，使用 Z3 求解器生成覆盖每条路径的具体测试输入。

## 架构

```
┌──────────────────────┐   ┌─────────────────────────────┐        ┌──────────────────────────┐        ┌──────────────────┐
│  generate_driver.py  │   │   TestGenAnalyzer.cpp       │        │       solve.py           │        │    codegen.py    │
│  (Driver Generator)  │   │   (CSA Checker)             │  JSON  │   (Z3 Constraint Solver) │  JSON  │  (C Test Writer) │
│                      │   │                             │ ──────>│                          │ ──────>│                  │
│  parse_signatures()  │──>│  checkBeginFunction         │  file  │  load_paths()            │        │  generate()      │
│  generate_driver()   │   │  checkEndFunction           │        │  get_constraints()       │        │  deduplicate()   │
│  → *_driver.c        │   │  checkEndAnalysis ──────────│        │  build_smt() / run_z3()  │        │  gen_test_call() │
└──────────────────────┘   │    writes JSON file         │        │  extract_model()         │        │  → test_autogen.c│
                           └─────────────────────────────┘        └──────────────────────────┘        └──────────────────┘
```

### generate_driver.py

为每个待分析的源文件生成 driver 文件，核心思路：

- 对每个函数生成 `driver_<func>()` 函数，用 `scanf` 读取标量参数，使 CSA 将其识别为外部符号输入（`conj_$N`）
- **关键**：driver 文件通过 `#include "<source.c>"` 将原始源文件内嵌到同一编译单元，确保 CSA 能跨调用追踪符号值
- 指针参数通过 `malloc`/`free` 分配真实内存，并尽量填入从 `scanf` 读取的值

**为什么必须同一编译单元？**

CSA 在函数入口为参数创建符号时，若参数来自 `scanf`（外部输入），会生成 `conj_$N` 符号（conjured symbol），这类符号可被 Z3 约束求解。若 driver 和目标函数在不同编译单元，CSA 无法追踪跨 TU 的符号值，参数会变成 `reg_$N`（register symbol），约束为空，无法求解。

**指针参数处理策略**

| 参数类型 | 处理方式 |
|----------|----------|
| `int`, `long`, `size_t`… | 直接 `scanf` 读取，传值 |
| `char *` / `const char *` | `malloc` 字符串缓冲区，`scanf %s` 读入，传指针，结束后 `free` |
| `int *`, `size_t *`… | `malloc sizeof(T)`，`scanf` 读入值后写入，传指针，结束后 `free` |
| `T **` (双指针) | `malloc` 内层 `T*`，若 T 为标量则再 `scanf` 填值，传二级指针，结束后 `free` |
| `void *` / 未知结构体指针 | `calloc` 固定大小缓冲区，零初始化，传指针，结束后 `free` |

生成的 driver 示例（`ascii_sum(const char *s)`）：

```c
static void driver_ascii_sum(void) {
    char s_buf[256] = {0};
    scanf("%255s", s_buf);
    char *s = (char *)malloc(strlen(s_buf) + 1);
    if (s) strcpy(s, s_buf);
    int _r = ascii_sum(s);
    (void)_r;
    free(s);
}
```

### TestGenAnalyzer.cpp

- `checkBeginFunction`：在函数入口收集所有参数（整数参数记录符号，指针参数标记 `is_scalar=false`）
- `checkEndFunction`：在函数出口提取路径约束，通过 `State->printJson` 获取 SMT-LIB 格式约束
- `checkEndAnalysis`：分析结束时将所有路径约束写入 JSON 文件

### solve.py

- 从 JSON 文件读取路径约束
- 提取 SMT-LIB 格式的约束表达式（由 CSA Z3 后端直接生成）
- 构建完整的 SMT-LIB 查询并调用 Z3 CLI 求解
- 解析 Z3 模型，将符号值映射回函数参数名
- 对指针参数（`is_scalar=false`）输出 `value=null`

### codegen.py

- 从 `test_inputs.json` 生成可编译的 C 单元测试文件
- 对指针参数传 `NULL`，对整数参数传 Z3 求解的具体值
- 去重策略：指针参数函数只保留 null-guard 路径（return -1），避免生成无法执行的测试

## 使用方法

### 单文件（原始用法）

```bash
cd /home/yanghq/llvm/llvm-project/build
bin/clang --analyze \
  -Xclang -analyzer-checker=testgen.TestGenAnalyzer \
  -Xclang -analyzer-constraints=z3 \
  <source.c>

/home/yanghq/csa-testgen/venv/bin/python3 \
  /home/yanghq/csa-testgen/solve.py \
  testgen_constraints.json
```

### 多文件项目（Driver 方法）

```bash
cd /home/yanghq/csa-testgen

# 一键运行：生成 driver → CSA 分析 → Z3 求解 → 生成测试代码
./run_project_testgen.sh test/cproject/sample_project

# 输出目录：test/cproject/sample_project/testgen_output/
#   ├── *_driver.c           每个源文件对应的 driver 文件
#   ├── *_constraints.json   每个源文件的路径约束
#   ├── all_constraints.json 合并后的约束
#   ├── test_inputs.json     Z3 求解结果
#   └── test_autogen.c       生成的 C 测试代码

# 编译并运行生成的测试
cd test/cproject/sample_project
gcc -std=c11 -D_GNU_SOURCE -Iinclude -Ivendor/miniz/include \
  src/utils.c src/decoder.c src/third_party_adapter.c src/parser.c \
  vendor/miniz/src/miniz_stub.c \
  testgen_output/test_autogen.c \
  -o testgen_output/test_autogen
./testgen_output/test_autogen
```

### 便捷脚本（单文件）

```bash
cd /home/yanghq/csa-testgen
./run_testgen.sh test/manual/test_multi_branch.c results.json
```

## 示例

### 单文件：整数参数函数

```c
int foo(int a, int b, int c) {
    if (a > 10) {
        if (b < a) {
            if (c == b + 5) { return 1; }
            else             { return 2; }
        } else { return 3; }
    } else { return 4; }
}
```

生成的测试输入：
```json
[
  {"path": 1, "function": "foo", "return_value": 4,
   "inputs": [{"name": "a", "value": 10}, {"name": "b", "value": 0}, {"name": "c", "value": 0}]},
  {"path": 4, "function": "foo", "return_value": 1,
   "inputs": [{"name": "a", "value": 11}, {"name": "b", "value": 10}, {"name": "c", "value": 15}]}
]
```

### 多文件项目：sample_project 验证结果（Driver 方法）

```
Results: 7 passed, 0 failed
```

生成的测试覆盖（11 条路径，7 条通过验证）：
- `clamp_int` 的 4 条路径（含 low>high、value<low、value>high、正常返回）
- `classify_record(NULL) -> -1`（null 检查路径）
- `decode_rle_frame(NULL, 0, NULL, 0, NULL) -> -1`（null 检查路径）
- `parse_sensor_line(NULL, NULL) -> -1`（null 检查路径）


## 工作原理

### 1. 约束提取

CSA 使用 `-analyzer-constraints=z3` 后端时，`State->printJson` 输出的约束直接是 SMT-LIB 格式：

```json
{ "symbol": "(conj_$2{int, LC1, S13485, #1}) > 10",
  "range":  "(bvsgt conj_$2 #x0000000a)" }
```

- `symbol`：约束的符号表示（人类可读）
- `range`：SMT-LIB 格式的约束表达式，可直接传给 Z3

### 2. 参数符号映射

CSA 在函数入口为每个参数创建 conjured symbol，格式为 `conj_$N{type, LC, S, #1}`。Checker 在 `checkBeginFunction` 时记录参数名到符号的映射，在 `checkEndFunction` 时将其写入 JSON：

```json
{"name": "a", "sym": "conj_$2{int, LC1, S13485, #1}", "type": "int"}
```

### 3. SMT 查询构建

`solve.py` 从约束中提取所有 `conj_$N` 符号，构建完整的 SMT-LIB 2 查询：

```smt2
(set-logic QF_BV)
(declare-fun |conj_$0| () (_ BitVec 32))
(declare-fun |conj_$1| () (_ BitVec 32))
(declare-fun |conj_$2| () (_ BitVec 32))
(assert (bvsgt |conj_$2| #x0000000a))
(assert (bvslt |conj_$1| |conj_$2|))
(assert (= |conj_$0| (bvadd |conj_$1| #x00000005)))
(check-sat)
(get-model)
```

注意：SMT-LIB 标识符不允许包含 `$`，因此用 `|...|` 引号包裹。

### 4. 模型解析

Z3 返回的模型形如：

```
sat
(model
  (define-fun |conj_$2| () (_ BitVec 32) #x0000000b)
  (define-fun |conj_$1| () (_ BitVec 32) #x0000000a)
  (define-fun |conj_$0| () (_ BitVec 32) #x0000000f)
)
```

`solve.py` 解析十六进制值并转换为有符号 int32，再按参数名映射输出。

## 中间文件格式

### testgen_constraints.json

```json
{
  "paths": [
    {
      "path": 1,
      "function": "foo",
      "params": [
        {"name": "a", "sym": "conj_$2{int, LC1, S13485, #1}", "type": "int"},
        {"name": "b", "sym": "conj_$1{int, LC1, S13485, #1}", "type": "int"},
        {"name": "c", "sym": "conj_$0{int, LC1, S13485, #1}", "type": "int"}
      ],
      "return_value": 4,
      "state_json": "\"program_state\": { ..., \"constraints\": [...] }"
    }
  ]
}
```

`state_json` 是 `State->printJson` 的原始输出，嵌入在 JSON 字符串中，`solve.py` 从中提取 `constraints` 数组。

## 支持的特性

| 特性 | 状态 | 说明 |
|------|------|------|
| 整数参数（int） | ✅ | 32-bit signed |
| 多分支条件 | ✅ | if/else 嵌套 |
| 参数间比较关系 | ✅ | `a > b`, `a == b` 等 |
| 算术表达式约束 | ✅ | `c == a + b`, `d == a * 2` 等 |
| 函数间调用 | ✅ | inter-procedural analysis |
| 递归函数 | ✅ | 受 CSA 递归深度限制 |
| 循环 | ⚠️ | 受 CSA 展开次数限制（默认 4 次） |
| 字符串指针（`char *`）| ✅ | malloc 缓冲区 + scanf 填入，CSA 可分析 null/内容路径 |
| 标量指针（`int *`等）| ✅ | malloc + scanf 填值，支持 out-parameter 路径 |
| 双指针（`T **`）| ✅ | 两层 malloc，内层标量用 scanf 初始化 |
| 不透明指针（`void *` / 结构体 `*`）| ⚠️ | calloc 零初始化缓冲区，CSA 分析 null-guard 路径 |
| 多文件项目 | ✅ | 通过 `run_project_testgen.sh` 支持 |
| C 测试代码生成 | ✅ | 通过 `codegen.py` 生成可编译的单元测试 |
| 结构体参数（值传递）| ❌ | 需扩展 Checker |
| 数组参数 | ❌ | 需扩展 Checker |

## 文件结构

```
/home/yanghq/llvm/llvm-project/
  └── clang/lib/StaticAnalyzer/Checkers/
      └── TestGenAnalyzer.cpp      # CSA Checker 实现

/home/yanghq/csa-testgen/
  ├── solve.py                     # Z3 求解器
  ├── codegen.py                   # C 测试代码生成器
  ├── generate_driver.py           # Driver 文件生成器
  ├── generate_compile_commands.py # compile_commands.json 生成器
  ├── run_testgen.sh               # 单文件便捷脚本
  ├── run_project_testgen.sh       # 多文件项目脚本（Driver 方法）
  ├── test/
  │   ├── manual/
  │   │   ├── test_multi_branch.c  # 多分支测试
  │   │   ├── test_multi_call.c    # 函数调用测试
  │   │   └── ...
  │   └── cproject/
  │       └── sample_project/      # 多文件项目测试用例
  │           ├── src/             # 源文件
  │           ├── include/         # 头文件
  │           ├── vendor/          # 第三方库
  │           └── testgen_output/  # 生成的测试输出
  │               ├── *_driver.c   # 生成的 driver 文件
  │               ├── *_constraints.json
  │               ├── all_constraints.json
  │               ├── test_inputs.json
  │               └── test_autogen.c
  └── README.md
```

## 依赖

- **LLVM/Clang 18**：需从源码构建，包含 TestGenAnalyzer checker
- **Z3**：命令行工具，`z3` 需在 PATH 中
- **Python 3.6+**：仅使用标准库，无额外依赖

## 已知限制

- **循环展开**：CSA 默认只展开 4 次循环，深层路径可能无法到达
- **路径爆炸**：复杂函数可能生成大量路径，导致分析时间过长
- **指针参数约束**：指针参数被记录但无法求解具体值，只能测试 null 检查路径
- **Z3 超时**：`solve.py` 中每个路径的求解超时为 30 秒

## 验证结果

### 单文件测试

所有生成的测试输入都经过验证，确保正确覆盖对应路径：

```bash
# test_multi_branch.c - 4 条路径全部正确
Path 1: foo(10, 0, 0) → return 4 ✓
Path 2: foo(11, 11, 0) → return 3 ✓
Path 3: foo(11, 10, -16) → return 2 ✓
Path 4: foo(11, 10, 15) → return 1 ✓

# test_multi_call.c - 函数间调用正确处理
test(-2147483647, 2147483647) → return 0 ✓
test(2359295, 2359300) → return 1 ✓
test(-2147352579, -2147352584) → return 1 ✓
test(29, 12) → return 0 ✓
```

### 多文件项目测试（sample_project - Driver 方法）

```bash
$ ./run_project_testgen.sh test/cproject/sample_project
=== CSA Multi-File Test Generation Pipeline (Driver Method) ===
[1/5] Using existing compile_commands.json
[2/5] Discovering source files...
[3/5] Generating drivers and running CSA...
  [1] src/utils.c
  [driver] utils.c -> utils_driver.c  (clamp_int, ascii_sum, parse_positive_int, split_kv)
  [TestGenAnalyzer] Wrote 7 paths to utils_constraints.json
  [2] src/decoder.c
  [driver] decoder.c -> decoder_driver.c  (decode_rle_frame)
  [TestGenAnalyzer] Wrote 1 paths to decoder_constraints.json
  [3] src/parser.c
  [driver] parser.c -> parser_driver.c  (parse_sensor_line, classify_record, parse_payload_packet)
  [TestGenAnalyzer] Wrote 3 paths to parser_constraints.json
[4/5] Merging constraints...
Merged 11 paths from 3 files
[5/5] Solving constraints and generating tests...
Solved 11 path inputs
Generated test_autogen.c (11 paths -> 11 after dedup)

$ cd test/cproject/sample_project && gcc ... && ./testgen_output/test_autogen
Results: 7 passed, 0 failed
```

生成的测试覆盖：
- `clamp_int` 的 4 条路径（含 low>high、value<low、value>high、正常返回）
- `classify_record(NULL) -> -1`（null 检查路径）
- `decode_rle_frame(NULL, 0, NULL, 0, NULL) -> -1`（null 检查路径）
- `parse_sensor_line(NULL, NULL) -> -1`（null 检查路径）

## 实现改进历史

### 初始方案：范围约束 + 手动翻译

**问题**：
- 需要手动解析 CSA 的范围约束字符串（如 `{ [11, 2147483647] }`）
- 需要区分比较符号和范围约束
- 需要递归解析表达式树并构建 Z3 AST
- 代码复杂度高（400+ 行），容易出错

**约束格式**：
```json
{"symbol": "(conj_$1) < (conj_$2)", "range": "{ [0, 0] }"}
{"symbol": "conj_$2", "range": "{ [11, 2147483647] }"}
```

### 改进 v1：Z3 后端 + SMT-LIB 直传

**优势**：
- 使用 `-analyzer-constraints=z3` 让 CSA 直接输出 SMT-LIB 格式
- 约束表达式可直接传给 Z3，无需手动翻译
- 代码简洁（200 行），逻辑清晰
- 支持 Z3 的所有 BitVec 理论特性

**约束格式**：
```json
{"symbol": "(conj_$1) < (conj_$2)", "range": "(bvslt conj_$1 conj_$2)"}
{"symbol": "conj_$2 > 10", "range": "(bvsgt conj_$2 #x0000000a)"}
```

**关键改进**：
1. **交互方式**：从 stdin/stdout 管道改为 JSON 文件，组件完全解耦
2. **约束处理**：从手动解析翻译改为直接使用 SMT-LIB，逻辑简化 50%+
3. **可维护性**：约束文件可读、可调试、可存档

### 改进 v2：Driver 方法解决多文件项目约束提取问题

**问题**：
- 多文件项目中，直接分析源文件时参数符号为 `reg_$N`（register symbol），约束为空
- 原因：CSA 在函数入口为参数创建符号时，若无外部输入标记，会使用 register symbol
- Register symbol 无法被 Z3 约束求解，导致所有路径的 `constraints: null`

**解决方案（Driver 方法）**：
1. 为每个源文件生成 driver 文件（`generate_driver.py`）
2. Driver 文件通过 `#include "<source.c>"` 将原始源文件嵌入同一编译单元
3. 对每个函数生成 `driver_<func>()` 函数，用 `scanf` 读取标量参数
4. CSA 分析 driver 文件时，识别 `scanf` 为外部输入，为参数创建 `conj_$N` 符号（conjured symbol）
5. Conjured symbol 可被 Z3 约束求解，成功提取路径约束

**为什么必须同一编译单元？**
- CSA 的符号执行是编译单元级别的，无法跨 TU 追踪符号值
- 若 driver 和目标函数在不同文件，CSA 无法将 `scanf` 的 conjured symbol 传递到目标函数
- 通过 `#include` 嵌入源文件，确保 driver 和目标在同一 TU，符号值可正确传递

**验证结果**：
- 同一文件：`conj_$2{int, LC2, S13695, #1}` + 正确约束 ✓
- 分离文件：`reg_$N` + `constraints: null` ✗

**关键改进**：
1. **符号类型**：从 `reg_$N`（无约束）改为 `conj_$N`（可求解）
2. **编译单元**：通过 `#include` 确保 driver 和目标在同一 TU
3. **自动化**：`run_project_testgen.sh` 自动生成 driver 并分析
4. **覆盖率**：sample_project 从 2 条路径提升到 11 条路径（7 条通过验证）

## 故障排查

### 问题：No paths found

**原因**：函数没有参数，或参数不是简单整数类型

**解决**：
- 确保被测函数有整数参数（`int`）
- 检查 Checker 是否正确识别参数符号（查看 JSON 中的 `params` 字段）

### 问题：Path is UNSAT

**原因**：约束不可满足（通常是 CSA 的过度近似导致）

**解决**：
- 检查约束是否合理（查看 `testgen_constraints.json` 中的 `constraints`）
- 可能是 CSA 的路径敏感分析产生了矛盾约束
- 尝试简化函数逻辑

### 问题：Z3 timeout

**原因**：约束过于复杂，Z3 无法在 30 秒内求解

**解决**：
- 增加 `solve.py` 中的超时时间（修改 `timeout=30` 参数）
- 简化函数逻辑，减少约束数量
- 检查是否有非线性约束（如乘法、除法）

### 问题：Checker 没有输出 JSON 文件

**原因**：
- 环境变量 `TESTGEN_OUTPUT` 指向的路径不可写
- 没有找到任何有参数的函数

**解决**：
- 检查输出路径权限
- 确认源文件中有带参数的函数
- 查看 stderr 输出中的 `[TestGenAnalyzer]` 消息

### 问题：生成的测试输入不正确

**原因**：
- Z3 模型解析错误
- 符号映射错误

**调试**：
```bash
# 查看生成的 SMT-LIB 查询（修改 solve.py，在 run_z3 前打印 smt_text）
# 手动运行 Z3 验证
echo "(set-logic QF_BV)
(declare-fun |conj_\$2| () (_ BitVec 32))
(assert (bvsgt |conj_\$2| #x0000000a))
(check-sat)
(get-model)" | z3 -in
```

## 库函数 Summary 补全机制（创新点）

### 问题背景

CSA 对大量标准库函数缺乏建模，典型案例是 `<ctype.h>` 中的字符分类函数（`isdigit`、`isalpha`、`isspace` 等）。当被分析代码包含如下循环时：

```c
int parse_positive_int(const char *s, int *out_value) {
    for (size_t i = 0; s[i] != '\0'; ++i) {
        if (!isdigit((unsigned char)s[i])) {
            return -2;         // 非数字字符路径
        }
        value = value * 10 + (s[i] - '0');
    }
    *out_value = value;
    return 0;                  // 全数字路径
}
```

CSA 将 `isdigit` 视为不透明函数调用：为其返回值创建 conjured symbol，但不向参数 `s[i]` 添加任何约束。结果是：
- 路径"isdigit 返回非零（数字字符）"无法约束 `s[i]` 在 `['0', '9']` 区间
- Z3 只能为 `s[i]` 找到任意字符（如 `'A'`、`'\q'`），使生成的测试用例在运行时走错分支
- `return 0`（全数字字符串）这条路径对应的测试用例永远无法通过验证

其根源是**库函数语义缺失**：CSA 不知道"isdigit 返回非零"意味着"参数在 ASCII 48–57 之间"。

### 解决方案：分析期库函数 Summary 注入

在 `generate_driver.py` 生成的 driver 文件中，系统头文件之后、源文件嵌入之前，注入一个专用 stub 头文件 `stubs/lib_stubs.h`：

```
生成的 driver 文件结构
─────────────────────────────────────────────────
#include <stdio.h>          ← 系统头（定义 isdigit 为宏）
#include <ctype.h>
                             ← ↓ 关键注入点
#include "stubs/lib_stubs.h"  ← 仅在 __clang_analyzer__ 下生效
                             ← ↑ 取消宏定义，提供显式 inline 实现
#include "/abs/path/to/utils.c"  ← 目标源（isdigit 调用现在走 stub）
─────────────────────────────────────────────────
```

`lib_stubs.h` 对每个未建模函数的处理模式如下（以 `isdigit` 为例）：

```c
#ifdef __clang_analyzer__   /* 仅静态分析时生效，不影响生产编译 */

#ifdef isdigit
#undef isdigit              /* 取消 ctype.h 的宏定义 */
#endif
static inline int isdigit(int c) {
    if (c >= 48 && c <= 57) return 1;   /* '0'–'9' */
    return 0;
}

#endif /* __clang_analyzer__ */
```

### 工作原理

1. **编译时无影响**：`__clang_analyzer__` 仅由 clang 的 `-analyze` 模式定义，正常编译时 stub 代码不可见，不引入任何符号冲突。

2. **宏覆盖顺序**：
   - 先 `#include <ctype.h>` → `isdigit` 被定义为宏
   - 再 `#include "lib_stubs.h"` → `#undef isdigit` + 提供 inline 函数
   - 再 `#include "utils.c"` → 内部的 `<ctype.h>` 因 include guard 被跳过
   - utils.c 中所有 `isdigit(x)` 调用解析为我们的 inline stub

3. **约束传播**：CSA 分析 stub 时，会沿 `c >= 48 && c <= 57` 的两条分支分别传播约束：
   - 进入 `return 1` 分支 → 约束 `derived_$N ∈ [48, 57]`
   - 进入 `return 0` 分支 → 约束 `derived_$N ∉ [48, 57]`

4. **Z3 求解效果**：有了 `[48, 57]` 区间约束，Z3 能为 `s[i]` 求出合法数字字符（如 `'1'`、`'5'`），从而生成通过验证的测试用例。

### 已实现的 Summary 列表

当前 `stubs/lib_stubs.h` 覆盖以下函数：

| 函数 | 头文件 | Summary 语义 |
|------|--------|-------------|
| `isdigit(c)` | `<ctype.h>` | `c ∈ [48, 57]`（`'0'`–`'9'`） |
| `isalpha(c)` | `<ctype.h>` | `c ∈ [65, 90] ∪ [97, 122]`（`A-Z`/`a-z`） |
| `isupper(c)` | `<ctype.h>` | `c ∈ [65, 90]`（`A-Z`） |
| `islower(c)` | `<ctype.h>` | `c ∈ [97, 122]`（`a-z`） |
| `isalnum(c)` | `<ctype.h>` | `isdigit(c) || isalpha(c)` |
| `isspace(c)` | `<ctype.h>` | `c ∈ {32, 9, 10, 13, 12, 11}`（空白字符） |
| `ispunct(c)` | `<ctype.h>` | printable 非字母数字非空格字符 |
| `isprint(c)` | `<ctype.h>` | `c ∈ [32, 126]`（可打印字符） |
| `isxdigit(c)` | `<ctype.h>` | 十六进制字符 `0-9`/`a-f`/`A-F` |
| `toupper(c)` / `tolower(c)` | `<ctype.h>` | 大小写转换 |
| `atoi(s)` | `<stdlib.h>` | 数字字符串到整数转换 |

### 扩展方法

对任意缺失建模的库函数，按以下步骤添加 summary：

1. 在 `stubs/lib_stubs.h` 的 `#ifdef __clang_analyzer__` 块内添加：
   ```c
   #ifdef <函数名>
   #undef <函数名>
   #endif
   static inline <返回类型> <函数名>(<参数列表>) {
       /* 用显式 if/else 分支编码函数的语义前后条件 */
   }
   ```

2. 确保 stub 的分支结构**直接体现输入约束**（例如用 `c >= 48 && c <= 57` 而非 `(unsigned)c - 48 <= 9`，后者 CSA 可能无法推导等价区间约束）。

3. 若函数有多个语义上独立的判定（如 `isalnum = isdigit || isalpha`），建议拆解为多个独立的 `if` 而非使用短路逻辑运算符，以便 CSA 的路径敏感分析能覆盖每条子路径。

### 验证结果（parse_positive_int）

注入 `isdigit` stub 后，`parse_positive_int` 的 `return 0`（全数字字符串）路径获得了正确约束，Z3 能够生成如 `"1"` 这样的合法数字字符串，测试用例从"全部走错分支"变为"覆盖所有返回值路径"。

## LLM 覆盖率缺口补全机制（创新点二）

### 问题背景：CSA 循环展开限制

CSA 对循环的处理采用有界展开策略（默认最多 4 次），这导致依赖多次迭代才能触发的分支永远无法被覆盖。典型案例是 `parse_positive_int` 中的溢出检测：

```c
for (size_t i = 0; s[i] != '\0'; ++i) {
    value = (value * 10) + (s[i] - '0');
    if (value > 1000000) return -3;   // 触发需要 7 次迭代
}
```

CSA 展开 4 次时，`value` 最大为 9999，`value > 1000000` 永远为假，`return -3` 路径从未被探索，相应测试用例缺失。

### 解决方案：gcov + LLM 覆盖率缺口补全

在 CSA 流水线末尾追加一个自动化的测试补全阶段，结合覆盖率测量和 LLM 语义推理，并通过外层迭代循环实现收敛。

#### 整体架构（fill_gaps.py）

```
外层迭代循环（最多 max_iter 轮，默认 3）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ┌─────────────────────────────────────────────────┐
  │ 每轮（Round N）                                  │
  │                                                  │
  │  1. 读取 uncovered_branches（来自 coverage JSON  │
  │     或上一轮 re-measure 结果）                   │
  │                                                  │
  │  2. 按函数分组未覆盖分支                         │
  │                                                  │
  │  3. 对每个函数（一次 LLM 调用）：                │
  │     ┌── build_prompt(func_src,                   │
  │     │       ALL branches in this func,           │
  │     │       existing_tests)                      │
  │     │                                            │
  │     │   LLM 返回：                               │
  │     │   {"test_cases": [                         │
  │     │     {"target_line": N,                     │
  │     │      "inputs": [...],                      │
  │     │      "expected_return": R}, ...]}          │
  │     │                                            │
  │     ├── 对每个 test_case：                       │
  │     │     validate_candidate(target_line)        │
  │     │       ← probe 编译 + gcov 验证目标行执行  │
  │     │     validate_return_value()                │
  │     │       ← 确认实际返回值                    │
  │     │     if ok: append_llm_tests()              │
  │     │       ← 追加到 test_autogen.c             │
  │     │                                            │
  │     └── 若所有 test_case 均失败，重试最多        │
  │         max_retries（默认 3）次                   │
  │                                                  │
  │  4. re-measure：重新编译 + gcov                  │
  │     → 获得最新 uncovered_branches                │
  │     → 统计 branches_covered（用于收敛判断）      │
  └─────────────────────────────────────────────────┘

终止条件（满足任意一条即停止）：
  ① uncovered_branches == []     所有分支已覆盖
  ② branches_covered 未增加      本轮无进展（真实不动点）
  ③ iteration >= max_iter        达到安全上限
```

#### 与旧版（单分支串行）的对比

| 特性 | 旧版（单 branch 粒度） | 新版（函数粒度 + 迭代） |
|------|----------------------|----------------------|
| LLM 调用粒度 | 每条 branch 一次调用 | 每个函数一次调用（覆盖该函数内所有未覆盖 branch） |
| 迭代策略 | 无（单次遍历快照） | 自动 while 循环，每轮 re-measure |
| 覆盖率更新 | 不更新（处理过时快照） | 每轮重新 measure，实时感知进展 |
| 收敛判断 | 无 | `branches_covered` 不增加时自动停止 |
| 冗余测试 | 可能生成（目标已被顺带覆盖） | 少（re-measure 去掉已覆盖的） |
| LLM 调用数（典型） | `N_branches × retries` | `N_funcs_per_round × rounds`（通常更少） |

#### 关键实现细节

**1. 函数粒度 prompt**

一次 LLM 调用涵盖函数内所有未覆盖 branch，LLM 可利用全局视角生成一次覆盖多条 branch 的输入：

```python
# 发给 LLM 的 prompt 示例（函数内有 3 条未覆盖 branch）
"""
Function: parse_sensor_line

Source:
```c
int parse_sensor_line(const char *line, SensorRecord *out_record) { ... }
```

Uncovered branches — generate one test input per branch:
  - Line 28: `if (n == 0 || n >= sizeof(local)) {`
  - Line 38: `while (tok != 0) {`
  - Line 62: `if (!(seen_id && seen_reading && seen_tag)) {`

Return JSON: {"test_cases": [{"target_line": N, "inputs": [...], "expected_return": R}, ...]}
"""
```

**2. 基于 branches_covered 的收敛判断**

未覆盖分支计数可能因新分支暴露而保持不变（例如一条长分支被覆盖后，其内部分支开始可见），因此用**已覆盖分支数**而非未覆盖列表长度来判断进展：

```python
# 每轮 re-measure 后
new_uncovered, branches_covered_this_round = _remeasure(data)

# 收敛判断：已覆盖数未增加 → 停止
if branches_covered_this_round <= prev_covered:
    break  # 真实不动点

prev_covered = branches_covered_this_round
```

**3. Probe 污染清理**

每轮 re-measure 前清理 probe 编译产物，避免旧 `.gcno` 文件被 gcov 的 glob 误选：

```python
for pattern in ("probe*", "ret_probe*"):
    for f in Path(work_dir).glob(pattern):
        f.unlink()
```

**4. test ID 无冲突追加**

多次运行时 test ID 不重复，扫描文件中已有最大 ID 后递增：

```python
ids = [int(m) for m in re.findall(r',\s*(9\d{4,})\s*\)\s*;', text)]
next_id = max(ids, default=89999) + 1
```

### 覆盖率测量模块（measure_coverage.py / _cov_utils.py）

`parse_uncovered_branches` 负责从 gcov 输出中提取未覆盖分支，处理两类情况：

| 情况 | gcov 行前缀 | 含义 | 处理方式 |
|------|------------|------|---------|
| 执行过但有分支未走到 | `N:` (N>0) | 该行被执行，但某个 branch 的 `taken 0` | 检查后续 branch 注释，只要有一条 `taken 0` 即报告 |
| 整行未执行 | `#####:` | 该行从未执行，所有分支均未覆盖 | 只要后续有 branch 注释即报告（无需逐条检查） |

这确保 `uncovered_branches` 列表与 `coverage_summary` 中的 `branches_covered` 数字一致，避免两者之间的统计矛盾。

### 运行结果（sample_project）

```
初始覆盖率（CSA 生成的测试，coverage_before.json）：
  utils.c         31/41 lines (75%)   34/42 branches (80%)
  decoder.c        7/10 lines (70%)    7/8  branches (87%)
  parser.c        29/75 lines (38%)   21/60 branches (35%)
  TOTAL           69/128 lines (53%)  62/110 branches (56%)
  → 22 uncovered branches

LLM 补全（fill_gaps.py, Round 1）：
  新增 2 个测试用例：
    parse_positive_int("1000001", &out) → -3  ← 溢出分支（需 7 次循环迭代）
    split_kv("key=value", "buf", 100, "buf", 1) → -3  ← 缓冲区容量检查

  re-measure 后（coverage_after.json）：
  utils.c         37/42 lines (88%)   39/42 branches (92%)  ← +6 lines, +5 branches
  TOTAL           75/129 lines (58%)  67/110 branches (60%)
  → 22 uncovered branches（counts same, 新暴露了 split_kv 内部分支）
  → branches_covered: 62 → 67（+5），触发 Round 2

LLM 补全（fill_gaps.py, Round 2）：
  所有函数尝试失败（parse_field、parse_sensor_line 等需要完整项目上下文）
  re-measure：branches_covered = 67，与 Round 1 持平 → 收敛，停止

最终：2 tests added, utils.c branch coverage 80% → 92%
```

### 使用方法

```bash
# 随流水线自动运行（run_project_testgen.sh 调用）
ANTHROPIC_API_KEY=sk-... ./run_project_testgen.sh <project_dir>

# 单独运行 fill_gaps.py（需要已有 coverage_data.json）
python3 fill_gaps.py coverage_before.json
python3 fill_gaps.py coverage_before.json --max-iter 5 --max-retries 3

# 干运行：只列出未覆盖分支，不调用 LLM
python3 fill_gaps.py coverage_before.json --dry-run

# 使用特定 Claude 模型
python3 fill_gaps.py coverage_before.json --model claude-opus-4-7
```

#### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `coverage_json` | （必填） | `measure_coverage.py` 生成的 JSON |
| `--max-iter` | 3 | 最大 measure→fill 轮数 |
| `--max-retries` | 3 | 每个函数的 LLM 调用重试次数 |
| `--model` | claude-sonnet-4-6 | Anthropic 模型 ID |
| `--dry-run` | false | 只检测，不补全 |

#### 生成覆盖率数据

```bash
# 先用 measure_coverage.py 生成 coverage_data.json
python3 measure_coverage.py \
    <test_autogen.c> <project_dir> <compile_commands.json> \
    --output coverage_before.json \
    --work-dir cov_work/

# 然后运行 fill_gaps.py 补全
python3 fill_gaps.py coverage_before.json

# 补全后再次测量对比效果
python3 measure_coverage.py \
    <test_autogen.c> <project_dir> <compile_commands.json> \
    --output coverage_after.json \
    --work-dir cov_work/

# 对比 before/after 覆盖率
python3 report_coverage.py coverage_before.json coverage_after.json
```

### 已知限制

- **probe 链接范围**：`validate_candidate` 只链接 `probe.c + 目标源文件`，跨文件调用（如 `parse_sensor_line` 调用 `split_kv`）无法通过 probe 验证，这类函数的测试补全会失败
- **结构体参数**：LLM 有时对结构体指针参数返回 dict 值，系统会将其规范化为零初始化的 `&local` 指针
- **不可达分支**：部分分支对应不可能的输入组合，`branches_covered` 收敛后自动停止，不会无限重试

### 1. 支持更多参数类型

**指针参数**：
- 修改 Checker 处理 `loc::MemRegionVal`
- 提取指针指向的内存区域约束
- 生成指针指向的具体值

**结构体参数**：
- 处理结构体字段的符号值
- 为每个字段生成独立的测试输入
- 支持嵌套结构体

**数组参数**：
- 提取数组元素的约束
- 生成数组的具体内容
- 处理数组长度约束

### 2. 优化路径选择

- 使用覆盖率引导减少冗余路径
- 优先选择高价值路径（如错误处理路径）
- 路径剪枝：过滤掉不可达或冗余路径

### 3. 并行求解

```python
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor() as executor:
    results = list(executor.map(solve_path, paths))
```

### 4. 增量求解

利用 Z3 的增量求解能力，复用公共约束：

```python
solver = Solver()
solver.add(common_constraints)
for path_specific in path_constraints:
    solver.push()
    solver.add(path_specific)
    if solver.check() == sat:
        model = solver.model()
    solver.pop()
```

### 5. 测试代码生成

自动生成可执行的单元测试代码：

```python
def generate_test_code(results):
    code = "#include <assert.h>\n\n"
    for r in results:
        args = ", ".join(str(i["value"]) for i in r["inputs"])
        code += f"assert({r['function']}({args}) == {r['return_value']});\n"
    return code
```

## 性能优化建议

1. **限制路径数量**：使用 `-analyzer-max-loop` 控制循环展开次数
2. **过滤函数**：只分析目标函数，跳过库函数
3. **缓存约束文件**：避免重复运行 CSA
4. **批量求解**：一次性求解多个路径

## 相关资源

- [Clang Static Analyzer 文档](https://clang.llvm.org/docs/ClangStaticAnalyzer.html)
- [Z3 Theorem Prover](https://github.com/Z3Prover/z3)
- [SMT-LIB 标准](http://smtlib.cs.uiowa.edu/)
- [CSA Checker 开发指南](https://clang.llvm.org/docs/analyzer/checkers.html)

## 贡献者

本工具基于 Clang Static Analyzer 和 Z3 Theorem Prover 开发，用于自动化测试用例生成研究。

## 许可

本项目遵循 LLVM 项目的许可协议。

