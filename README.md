# QuinLang (QL)

QuinLang is a tiny, C-style toy language and compiler that I built to learn about parsing, type checking, and code generation from the ground up.

The project now has **two backends**:

- An original 8086/DOS backend that spits out real-mode `.COM` binaries and runs them under DOSBox.
- A newer, self-contained **QuinVM** bytecode interpreter written in Python, which is the default and requires no external tools.

The language is intentionally small but surprisingly capable:

- `int`, `bool`, `str`, `ptr`, and fixed-size stack arrays `int[N]`
- Functions with parameters and `int`/`void` returns
- `if` / `else`, `while`
- Arithmetic, comparisons, and short-circuit `&&` / `||`
- Built-in `print` / `println`
- Pointer intrinsics: `load16`, `store16`, `memcpy`, `memset`
- Array helpers: `array_push`, `array_pop`

This README walks through how to build and run QL code, what the language supports, and how the compilation pipeline is wired up.

---

## Getting started

### Prerequisites

- Python 3.10+ (for the QuinVM backend)

The old 8086 backend additionally expects:

- NASM
- DOSBox-X

You don’t need those if you only care about running on QuinVM, which is the default path now.

### Running a QL program on the VM

From the project root:

```bash path=null start=null
python -m compiler.driver_vm examples/hello.ql
```

You should see output similar to:

```text path=null start=null
30201043211111789000 
Hello
My Name Is Nathan1
2
```

That program exercises arrays, `array_push` / `array_pop`, pointers, memory intrinsics, printing, and boolean logic all in one go.

If you just want a sanity check:

```bash path=null start=null
python -m compiler.driver_vm examples/vm_test.ql
# -> 42
```

### (Optional) Running via the 8086/DOS backend

If you have NASM and DOSBox-X installed and want to see real-mode `.COM` binaries in action, there is still a script for that in the repo (8086 backend). The VM is the preferred path going forward, but the 8086 codegen is kept around as a reference and for fun.

---

## Language overview

QuinLang is intentionally close to “baby C” with a few constraints to keep everything manageable.

### Types

Supported types:

- `int` – 16-bit signed integer
- `bool` – boolean (`true` / `false`), stored in a 16-bit slot
- `str` – interned string id in the VM; printed via a string table
- `ptr` – generic 16-bit pointer (used with `load16`/`store16`/`memcpy`/`memset`)
- `void` – no value
- `int[N]` – fixed-size array of `N` `int` elements stored on the stack

There’s no heap or dynamic allocation. All arrays are fixed-size and live in the current stack frame.

### Functions

```quin path=null start=null
fn name(param1: Type1, param2: Type2, ...): ReturnType {
    // statements
}
```

- `name` is the function identifier.
- Parameters are `name: Type` pairs separated by commas.
- `ReturnType` can be omitted for `void` functions.
- The entry point must be:

```quin path=null start=null
fn main(): int {
    // ...
    return 0;
}
```

### Variables and statements

Variable declarations:

```quin path=null start=null
let x: int;
let x: int = 42;
let msg: str;
let p: ptr;
let a: int[3];
```

Assignments:

```quin path=null start=null
x = 5;
x = x + 1;
a[0] = 10;
a[i] = x;
```

`if` / `else` and `while` look like you would expect:

```quin path=null start=null
if (condition) {
    // then
} else {
    // else (optional)
}

while (condition) {
    // body
}
```

`condition` must type-check as `bool`. Under the hood everything is 0/1.

Return statements:

```quin path=null start=null
return;
return 0;
return x + 1;
```

- In `void` functions, `return;` just exits.
- In non-void functions, you must return an expression of the right type.

Any bare expression followed by `;` is an expression statement:

```quin path=null start=null
some_fn();
array_push(a, len, 10);
```

### Expressions

Literals:

```quin path=null start=null
123
0xFF      // hex int
"Hello"   // string literal (VM backend)
true
false
```

Variables and identifiers:

```quin path=null start=null
x
my_var
```

Unary operators:

```quin path=null start=null
-x       // arithmetic negation
!flag    // logical not
&x       // address-of (see pointers below)
```

Binary arithmetic:

```quin path=null start=null
x + y
x - y
x * y
x / y
```

Binary comparisons (produce `bool`):

```quin path=null start=null
x == y
x != y
x < y
x <= y
x > y
x >= y
```

Logical operators with short-circuit:

```quin path=null start=null
za && zb
za || zb
```

- `&&` and `||` are **short-circuiting**, so the right-hand side is only evaluated when needed.
- Precedence is `!` > comparisons > `&&` > `||`, roughly C-like.

Function calls:

```quin path=null start=null
foo();
bar(1, 2);
println(42);
```

### Arrays

Arrays are fixed-size `int[N]` values stored directly on the stack. There is no resizing or reallocation.

Declare and use an array:

```quin path=null start=null
fn main(): int {
    let a: int[3];
    let i: int;

    a[0] = 10;
    a[1] = 20;
    a[2] = 30;

    i = 0;
    while (i < 3) {
        println(a[i]);
        i = i + 1;
    }

    return 0;
}
```

Key points:

- Type is always `int[N]` for some literal `N`.
- Indexing uses `array[index]` syntax.
- Index must be an `int`.
- There’s currently **no bounds checking**.

#### `array_push` / `array_pop`

Arrays are paired with an explicit `len: int` that tracks how many slots are “in use”:

```quin path=null start=null
let arr: int[3];
let len: int;
let v: int;

len = 0;
len = array_push(arr, len, 10);
len = array_push(arr, len, 20);
len = array_push(arr, len, 30);

v = array_pop(arr, len);
len = len - 1;
println(v);  // 30
```

- `array_push(arr, len, value)` writes `value` to `arr[len]` and returns `len + 1`.
- `array_pop(arr, len)` returns `arr[len - 1]`.
- You are responsible for tracking `len` and staying within the fixed capacity of the array.

### Pointers and memory intrinsics

QuinLang exposes a very small pointer/memory API. Pointers are just 16-bit integers with type `ptr`.

Taking addresses:

```quin path=null start=null
let x: int;
let a: int[3];
let p: ptr;

p = &x;       // pointer to scalar
p = &a[1];    // pointer to array element
```

Low-level memory helpers:

```quin path=null start=null
// Read a 16-bit word
load16(p: ptr): int

// Write a 16-bit word
store16(p: ptr, value: int): void

// Copy raw bytes
memcpy(dst: ptr, src: ptr, count: int): void

// Fill raw bytes
memset(dst: ptr, value: int, count: int): void
```

Example of using them together:

```quin path=null start=null
fn main(): int {
    let a: int;
    let b: int;
    let pa: ptr;
    let pb: ptr;

    a = 1234;
    b = 0;

    pa = &a;
    pb = &b;

    store16(pa, 4321);
    println(a);          // 4321

    store16(pb, 1111);
    println(b);          // 1111

    let buf1: int[3];
    let buf2: int[3];

    buf1[0] = 7;
    buf1[1] = 8;
    buf1[2] = 9;

    // 3 ints * 2 bytes = 6 bytes
    memcpy(&buf2[0], &buf1[0], 6);

    println(buf2[0]);    // 7
    println(buf2[1]);    // 8
    println(buf2[2]);    // 9

    memset(&buf2[0], 0, 6);

    println(buf2[0]);    // 0
    println(buf2[1]);    // 0
    println(buf2[2]);    // 0

    return 0;
}
```

On the 8086 backend these truly operate on bytes. On QuinVM they operate on a locals array, but the surface semantics are the same.

---

## Compilation pipeline

At a high level, the compiler does this:

1. **Lexing** – Convert the source text into a stream of tokens (`fn`, identifiers, numbers, `{`, `}`, etc.).
2. **Parsing** – Turn tokens into an abstract syntax tree (AST) of expressions and statements.
3. **Semantic analysis** –
   - Resolve variable and function names.
   - Enforce type rules (e.g. `int` vs `bool`, correct function arguments, array element types).
   - Attach types to every expression node.
4. **Code generation** – Lower the typed AST into either:
   - 16-bit 8086 assembly (original backend), or
   - A compact QuinVM bytecode sequence.
5. **Execution** –
   - For the VM backend, the Python `QuinVM` interpreter runs the bytecode directly.
   - For the 8086 backend, the generated assembly is assembled and run under DOSBox.

### QuinVM bytecode

The VM backend lives in two main modules:

- `compiler/bytecode.py` – defines the `OpCode` enum and `Instruction` objects.
- `runtime/vm.py` – implements the `QuinVM` interpreter.

The bytecode is deliberately minimal:

- Stack/locals: `PUSH_INT`, `LOAD_LOCAL`, `STORE_LOCAL`, `LOAD_LOCAL_IDX`, `STORE_LOCAL_IDX`
- Arithmetic: `ADD`, `SUB`, `MUL`, `DIV`, `NEG`
- Comparisons: `CMP_EQ`, `CMP_NE`, `CMP_LT`, `CMP_LE`, `CMP_GT`, `CMP_GE`
- Logic: `NOT`, plus control-flow `JMP`, `JZ`, `JNZ`
- Calls: `CALL`, `RET` with a simple calling convention (args on stack, return value on stack)
- Pseudo-pointer ops on locals: `LOAD_INDIRECT`, `STORE_INDIRECT`, `MEMCPY_LOCALS`, `MEMSET_LOCALS`
- I/O: `PRINT_INT`, `PRINT_STR`, `PRINTLN_INT`, `PRINTLN_STR`

`codegen_vm.py` walks the AST and emits these instructions. Each QL function gets a `FunctionInfo` that records its entry point, local count, and parameter count so `CALL`/`RET` can set up frames correctly.

### 8086 backend (historical)

The 8086 backend follows the same front-end (lexer/parser/sema) but generates NASM assembly instead. It uses a small runtime (`runtime/*.asm`) for printing and string handling.

This backend was the original implementation and served as the reference for the VM. It’s still useful if you want to see how the same language maps down to real hardware, but day-to-day development can live entirely on QuinVM.

---

## Project layout

Rough structure of the repo:

- `compiler/`
  - `lexer.py`, `tokens.py` – lexical analysis
  - `parser.py` – recursive-descent parser that builds the AST
  - `ast.py` – node definitions
  - `types.py` – type objects and helpers
  - `sema.py` – semantic analysis and type checking
  - `builtins.py` – builtin function signatures
  - `codegen_8086.py` – 8086/DOS codegen
  - `codegen_vm.py` – QuinVM codegen
  - `bytecode.py` – bytecode opcodes and `Instruction`
  - `driver.py` – CLI entry point for the 8086 backend
  - `driver_vm.py` – CLI entry point for the VM backend
- `runtime/`
  - `vm.py` – QuinVM interpreter
  - `*.asm` – 8086 runtime support (print, strings, etc.)
- `examples/`
  - Small QL programs demonstrating features (`hello.ql`, `vm_test.ql`, `vm_arrays*.ql`, `control_flow.ql`, ...)

---

## Limitations and future ideas

QL is intentionally small and has some rough edges:

- No heap or dynamic allocation; only fixed-size stack arrays.
- No bounds checking on array indexing or `array_push`/`array_pop`.
- `ptr` is untyped; you are responsible for pointing at the right thing.
- Only 16-bit `int`; no 32-bit or 64-bit types yet.

Some obvious future directions:

- A simple module system and separate compilation.
- A tagged `enum` / `union` type.
- A tiny standard library layered on top of the VM.

For now, the goal is to keep the compiler and VM simple enough that you can read through them in one sitting and see exactly how each language feature works end-to-end.