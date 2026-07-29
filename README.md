# QuinLang (QL)

QuinLang is a tiny, C-style language and compiler that I built to learn about parsing, type checking, and code generation from the ground up.

The project has **two backends**:

- **QuinVM** — a self-contained bytecode compiler and interpreter written in Python. This is the default and only supported path; it needs no external tools.
- **8086/DOS** — the original backend, which emits NASM assembly for real-mode `.COM` binaries. It is kept as a reference and is now well behind the language (see [Backend status](#backend-status)).

The language is intentionally small:

- `int`, `bool`, `str`, `ptr`, and fixed-size stack arrays `int[N]`
- Functions with parameters, recursion, and `int` / `bool` / `str` / `ptr` / `void` returns
- `if` / `else`, `while`
- Arithmetic (`+ - * / %`), comparisons, and short-circuit `&&` / `||`
- `print` / `println` statements for `int`, `str`, and `bool`
- Multi-file programs via `include`, plus a small `std/` library
- Pointer intrinsics: `load16`, `store16`, `memcpy`, `memset`
- Heap intrinsics: `alloc`, `heap_load`, `heap_store`
- Array helpers: `array_push`, `array_pop`
- Constant-time-style helpers: `ct_eq`, `ct_select`
- Inline VM bytecode via `vm_asm { ... }`, inline 8086 assembly via `asm "..."`

For the precise grammar and the full built-in reference, see [SYNTAX.md](SYNTAX.md).

---

## Getting started

### Prerequisites

- Python 3.10+ (tested on 3.12). No third-party packages.

The 8086 backend additionally expects NASM and DOSBox-X, but you don't need either to use QuinLang.

### Running a QL program

From the project root:

```bash
python3 -m compiler.driver_vm examples/vm_test.ql
# -> 42
```

The driver lexes, resolves `include`s, type-checks, compiles to bytecode, and runs it in-process. Compile errors are reported as `Import error:`, `Semantic error:`, or `Codegen error:` with a `[line:col]` prefix; runtime faults come out as `Runtime error:`.

A larger tour of arrays, pointers, printing, and boolean logic:

```bash
python3 -m compiler.driver_vm examples/hello.ql
```

Other examples worth reading: `examples/control_flow.ql` (short-circuit operators), `examples/vm_arrays_push.ql` (`array_push`), `examples/vm_asm_example.ql` (inline bytecode), `examples/ct_primitives.ql` (`ct_eq` / `ct_select`).

Note that `main`'s return value is computed by the VM but **not** propagated to the process exit code — the driver always exits 0 on a successful run.

### (Optional) the 8086/DOS backend

```bash
python3 -m compiler.driver examples/hello.ql -o build/out.asm
```

This only writes assembly; assembling with NASM and running under DOSBox is left to you. See [Backend status](#backend-status) before relying on it.

---

## Multi-file programs

A file may begin with `include` statements, which must appear **before** any function definition:

```quin
include "std/math.ql";
include "./helpers.ql";

fn main(): int {
    println(max(3, 9));   // 9
    return 0;
}
```

- Paths starting with `std/` resolve against the project's `std/` directory.
- Any other path resolves relative to the file containing the `include`.
- Includes are resolved depth-first; repeats and cycles are collapsed to a single copy.
- Defining the same function name in two files is an error.

`std/` currently ships `math.ql` (`abs`, `min`, `max`, `clamp`). `std/io.ql` and `std/prelude.ql` exist but are empty.

---

## Language overview

This is a quick tour; [SYNTAX.md](SYNTAX.md) is the reference.

### Types

- `int` — 16-bit **signed** integer. Arithmetic wraps (`32767 + 1` is `-32768`), and `/` truncates toward zero.
- `bool` — `true` / `false`. Not interchangeable with `int`: conditions must be `bool`, and `true + 1` is a type error.
- `str` — a string literal. On the VM this is an interned id into a string table.
- `ptr` — an untyped address. See [Pointers and memory](#pointers-and-memory) for what it actually holds.
- `void` — no value; only valid as a return type.
- `int[N]` — a fixed-size array of `N` ints in the current frame, for a literal `N > 0`.

Arrays are deliberately second-class: they cannot be parameters, return types, initialized at declaration, assigned as a whole, or used as a value. They are zeroed at declaration and filled element by element.

### Functions

```quin
fn name(param1: Type1, param2: Type2): ReturnType {
    // statements
}
```

Omitting `: ReturnType` makes the function `void`. Functions may be called before they are defined, and may recurse. A non-void function must return on every path, or you get `Function 'f' missing return statement`.

The entry point is `main`, which takes no parameters and returns `int` or `void`:

```quin
fn main(): int {
    return 0;
}
```

### Variables and statements

```quin
let x: int;            // zero-initialized
let x: int = 42;
let y = 42;            // type inferred from the initializer
let a: int[3];         // zeroed, no initializer allowed
```

Assignment targets are a variable or an array element:

```quin
x = 5;
a[i] = x;
```

Control flow is C-shaped, but the condition must type-check as `bool` — there is no "nonzero is true":

```quin
if (x > 0) {
    // ...
} else {
    // ...
}

while (i < 3) {
    i = i + 1;
}
```

Blocks introduce a scope, so an inner `let` may shadow an outer one; redeclaring a name in the *same* scope is an error.

`print` and `println` are statements with call-like syntax (not functions you can pass around). They accept `int`, `str`, or `bool`; a `bool` prints as `true` / `false`:

```quin
println(42);
println("Hello");
println(true);
```

### Expressions

```quin
123        0xFF        "text"       true      false
-x         !flag       &x
a + b      a - b       a * b        a / b     a % b
a == b     a != b      a < b        a <= b    a > b     a >= b
a && b     a || b
foo(1, 2)  arr[i]
```

Precedence, tightest first: postfix `()` / `[]`, then unary `! - &`, then `* / %`, then `+ -`, then relational `< <= > >=`, then equality `== !=`, then `&&`, then `||`. `&&` and `||` short-circuit. Comparisons require both sides to have the same type and produce `bool`.

Integer literals are 16-bit and must fit in `0..65535`; there are no negative literals, only the unary `-` operator. `65535` and `-1` are the same value, and both print as `-1`.

### Arrays

```quin
fn main(): int {
    let a: int[3];
    let i: int;

    a[0] = 10;
    a[1] = 20;
    a[2] = 30;

    while (i < 3) {
        println(a[i]);
        i = i + 1;
    }

    return 0;
}
```

There is **no bounds checking**. An index that runs past the end of the array quietly reads or writes a neighboring local; the VM only faults when the index leaves the frame entirely.

`array_push` / `array_pop` pair an array with an explicit length you maintain yourself:

```quin
let arr: int[3];
let len: int;
let v: int;

len = array_push(arr, len, 10);   // writes arr[len], returns len + 1
len = array_push(arr, len, 20);

v = array_pop(arr, len);          // reads arr[len - 1], does NOT update len
len = len - 1;
println(v);                       // 20
```

Both take the array by name — an arbitrary expression that happens to be an array won't work.

### Pointers and memory

`ptr` is untyped, and on the VM it is **an index into the current frame's locals**, not a machine address:

```quin
let x: int;
let a: int[3];
let p: ptr;

p = &x;        // slot of x
p = &a[1];     // slot of a, plus 1
println(load16(p));
store16(p, 4321);
```

Because addresses are slot indices, `memcpy` / `memset` counts are measured in **slots (16-bit words)** on the VM, not bytes:

```quin
let src: int[3];
let dst: int[3];

memcpy(&dst[0], &src[0], 3);   // 3 slots, not 6 bytes
memset(&dst[0], 0, 3);
```

(The 8086 backend really does count bytes here — one of several places the two backends disagree.)

A pointer only makes sense inside the frame that produced it: returning `&x` from a function and dereferencing it in the caller reads whatever local happens to occupy that slot, or faults with `Local index out of range` if the caller's frame is smaller.

### The heap

`alloc` carves out of a separate 64 KiB byte-addressed heap and is word-accessed through `heap_load` / `heap_store`:

```quin
let p: ptr;
p = alloc(2);          // size in bytes, rounded up to a multiple of 2
heap_store(p, 1234);
println(heap_load(p)); // 1234
```

The allocator is a bump pointer with no `free`, and it runs out at 64 KiB.

**Heap addresses and `&`-pointers share the type `ptr` but live in different address spaces.** `load16` on an `alloc`ed pointer reads a local, and `heap_load` on `&x` reads the heap; neither is diagnosed. Keep the two kinds of pointer straight yourself.

### Inline assembly

`vm_asm { ... }` drops to VM bytecode and is executed only by the VM backend:

```quin
let x: int = 5;
vm_asm {
    load_local x;
    push_int 1;
    add;
    store_local x;
}
println(x);   // 6
```

`asm "mov ax, 1";` splices raw 8086 assembly and is only emitted by the 8086 backend — the VM parses it and ignores it. The supported `vm_asm` instruction set is listed in [SYNTAX.md](SYNTAX.md#vm_asm-instruction-set).

---

## Backend status

The front end (lexer, parser, resolver, sema) is shared. The two code generators are not at parity:

| Feature | QuinVM | 8086 |
| --- | --- | --- |
| Arithmetic `+ - * /` | yes | yes |
| Modulo `%` | yes | **silently wrong** (no instruction emitted) |
| Comparisons, `&&`, `\|\|` | yes | yes |
| `if` / `while`, recursion | yes | yes |
| Function arguments | yes | **not passed** |
| `print` / `println` of `bool` | `true` / `false` | prints `1` / `0` |
| Arrays, `array_push` / `array_pop` | yes | yes |
| `load16` / `store16` / `memcpy` / `memset` | slot-based | byte-based |
| `ct_eq` / `ct_select` | yes (branchy) | yes (branchless) |
| `alloc` / `heap_load` / `heap_store` | yes | **calls a missing symbol** |
| `vm_asm` | yes | rejected |
| `asm "..."` | ignored | yes |
| String literals | printed verbatim | need a `$` terminator |

Treat the 8086 backend as a historical artifact: it is useful for seeing how the same front end maps onto real hardware, and it is not maintained feature-for-feature.

---

## Compilation pipeline

1. **Lexing** (`compiler/lexer.py`, `tokens.py`) — source text to tokens, with `//` comments, decimal and `0x` hex literals, and 16-bit range checks.
2. **Parsing** (`compiler/parser.py`, `ast.py`) — recursive descent into an AST. Every node carries `line` / `col`.
3. **Include resolution** (`compiler/resolver.py`) — recursively parses included files, detects cycles, and merges everything into one `Program`.
4. **Semantic analysis** (`compiler/sema.py`) — scopes and name resolution, the entry-point contract, the array restrictions, return checking, and a type for every expression node, recorded in a `Context` keyed by node identity.
5. **Code generation** — `compiler/codegen_vm.py` to bytecode, or `compiler/codegen_8086.py` to NASM.
6. **Execution** — `runtime/vm.py` interprets the bytecode; the 8086 path stops at generated assembly.

### QuinVM bytecode

`compiler/bytecode.py` defines the `OpCode` enum and `Instruction`; `runtime/vm.py` implements the interpreter. Values are 16-bit words held as ints masked to `0..0xFFFF`, sign-extended by anything that cares.

- Stack and locals: `PUSH_INT`, `LOAD_LOCAL`, `STORE_LOCAL`, `LOAD_LOCAL_IDX`, `STORE_LOCAL_IDX`, `POP`, `DUP`, `SWAP`
- Arithmetic: `ADD`, `SUB`, `MUL`, `DIV`, `MOD`, `NEG`
- Comparisons: `CMP_EQ`, `CMP_NE`, `CMP_LT`, `CMP_LE`, `CMP_GT`, `CMP_GE`
- Logic and control flow: `NOT`, `JMP`, `JZ`, `JNZ`
- Calls: `CALL`, `RET`
- Frame-relative pointers: `LOAD_INDIRECT`, `STORE_INDIRECT`, `MEMCPY_LOCALS`, `MEMSET_LOCALS`
- Heap: `ALLOC`, `HEAP_LOAD`, `HEAP_STORE`
- I/O: `PRINT_INT`, `PRINT_STR`, `PRINTLN_INT`, `PRINTLN_STR`

Calling convention: arguments are pushed left to right and consumed by `CALL` into the callee's leading locals. **Every** function pushes exactly one return value — void functions and void builtins push a dummy `0` that the caller pops — so `RET` is uniform. Each frame records the operand-stack height at entry, and `RET` verifies the balance, which turns a codegen bug into an immediate `Unbalanced operand stack at RET` instead of silent corruption.

Codegen assigns a distinct slot to every parameter and every declaration, never reusing slots across sibling scopes, so shadowed names cannot collide. Arrays occupy `N` consecutive slots.

The VM checks local indices, heap word bounds, operand-stack underflow, division and modulo by zero, and negative `memcpy` / `memset` counts. It does not check array bounds.

---

## Project layout

- `compiler/`
  - `lexer.py`, `tokens.py` — lexical analysis
  - `parser.py` — recursive-descent parser
  - `ast.py` — node definitions
  - `compiler_types.py` — `Type` objects, array-name parsing, helpers
  - `resolver.py` — `include` resolution and AST merging
  - `sema.py` — semantic analysis and type checking
  - `builtins.py` — built-in function signatures
  - `bytecode.py` — opcodes and `Instruction`
  - `codegen_vm.py` — QuinVM codegen
  - `codegen_8086.py`, `layout.py`, `emitter.py` — 8086/DOS codegen and stack layout
  - `driver_vm.py` — CLI entry point for the VM (default)
  - `driver.py` — CLI entry point for the 8086 backend
  - `ir.py` — an unused sketch of a linear IR
- `runtime/`
  - `vm.py` — the QuinVM interpreter
  - `*.asm`, `*.inc` — 8086 runtime support (printing, strings, math)
- `std/` — `math.ql`; `io.ql` and `prelude.ql` are placeholders
- `examples/` — small QL programs
- `tests/` — one 8086 fixture; there is no automated test suite yet
- `tools/` — `build.ps1` and `disasm.ps1` are currently empty

---

## Limitations and gotchas

- No bounds checking on array indexing or `array_push` / `array_pop`; an in-frame overrun silently hits a neighboring local.
- `ptr` is untyped and overloaded: frame-slot pointers and heap addresses are the same type but different address spaces.
- Pointers don't outlive the frame they point into.
- The heap is a bump allocator with no `free`.
- `int` is the only numeric type: 16-bit, signed, wrapping.
- Comparing `str` values compares interned string ids, so `==` and `!=` behave sensibly but `<` / `>` are meaningless (`"b" < "a"` is `true`).
- `main`'s return value never reaches the process exit code.
- The 8086 backend is incomplete — see the table above.
- No automated tests.

Future directions: `for` loops and `break` / `continue`, a real bounds-checked array or slice type, distinct pointer types, filling out `std/`, and a test suite.

The goal is to keep the compiler and VM small enough to read in one sitting and see exactly how each language feature works end to end.
