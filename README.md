# QuinLang (QL)

QuinLang is a tiny, C-style language and compiler that I built to learn about parsing, type checking, and code generation from the ground up.

It compiles to bytecode for **QuinVM**, a stack machine written in Python. The whole toolchain is one `python3 -m` invocation with no third-party dependencies.

The language is intentionally small:

- `int`, `bool`, `str`, `ptr`, `heapptr`, and fixed-size stack arrays `int[N]`
- Functions with parameters, recursion, and `int` / `bool` / `str` / pointer / `void` returns
- `if` / `else`, `while`, `for`, `break` / `continue`, and bare `{ ... }` blocks
- Arithmetic (`+ - * / %`), comparisons, and short-circuit `&&` / `||`
- `print` / `println` statements for `int`, `str`, and `bool`
- Multi-file programs via `include`, plus a small `std/` library
- Frame-pointer intrinsics: `load16`, `store16`, `memcpy`, `memset`
- Heap intrinsics: `alloc`, `heap_load`, `heap_store`
- Array helpers: `array_push`, `array_pop`
- Constant-time-style helpers: `ct_eq`, `ct_select`
- Inline bytecode via `vm_asm { ... }`

For the precise grammar and the full built-in reference, see [SYNTAX.md](SYNTAX.md).

> **History.** QuinLang originally targeted 16-bit 8086 real mode, emitting NASM for DOS `.COM` binaries. That backend was removed once it had fallen far enough behind the language to silently miscompile valid programs. It is preserved at the tag [`v0-8086-backend`](../../tree/v0-8086-backend) — check out or browse that tag to see `codegen_8086.py`, the `runtime/*.asm` support code, and the `asm "..."` inline-assembly statement.

---

## Getting started

### Prerequisites

Python 3.10+ (tested on 3.12). Nothing else.

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

Other examples worth reading: `examples/control_flow.ql` (short-circuit operators), `examples/for_loops.ql` (`for`, `break` / `continue`, blocks), `examples/vm_arrays_push.ql` (`array_push`), `examples/vm_asm_example.ql` (inline bytecode), `examples/ct_primitives.ql` (`ct_eq` / `ct_select`).

Note that `main`'s return value is computed by the VM but **not** propagated to the process exit code — the driver always exits 0 on a successful run.

### Running the tests

```bash
python3 -m unittest discover -s tests -t .
```

287 tests covering the lexer, parser, resolver, type checker, code generator, and VM. They run in about a tenth of a second, so there's no reason not to run them on every change. See [Tests](#tests) for the layout.

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
- `str` — a string literal, held as an interned id into a string table.
- `ptr` — an address in the current frame, produced by `&`.
- `heapptr` — an address in the heap, produced by `alloc`.
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

for (let i = 0; i < 3; i = i + 1) {
    println(i);
}
```

Every `for` clause is optional. The init may be a `let` or an assignment, and `for (;;)` loops until something breaks out. The loop variable is scoped to the loop, so two loops in a row may both declare `i`.

`break` leaves the innermost enclosing loop; `continue` skips to its next iteration. In a `for`, `continue` still runs the step clause, so the loop advances:

```quin
for (let i = 0; i < 6; i = i + 1) {
    if (i == 4) { break; }
    if (i == 1) { continue; }
    println(i);              // 0 2 3
}
```

Using either outside a loop is a compile error.

Blocks introduce a scope, so an inner `let` may shadow an outer one; redeclaring a name in the *same* scope is an error. A bare block is a statement, useful when you want a scope and nothing else:

```quin
let x: int = 1;
{
    let x: int = 2;   // shadows the outer x
    println(x);       // 2
}
println(x);           // 1
```

`print` and `println` are statements with call-like syntax (not functions you can pass around). They accept `int`, `str`, or `bool`; a `bool` prints as `true` / `false`:

```quin
println(42);
println("Hello");
println(true);
```

### Expressions

```quin
123        0xFF        "text"       true      false     null
-x         !flag       ~x           @x
a + b      a - b       a * b        a / b     a % b
a ^ b      a | b       a & b        a << b    a >> b
a == b     a != b      a < b        a <= b    a > b     a >= b
a && b     a || b
foo(1, 2)  arr[i]
```

Precedence, tightest first: postfix `()` / `[]`, then unary `! - ~ @`, then `* / %`, then `+ -`, then `<< >>`, then relational `< <= > >=`, then equality `== !=`, then `&`, then `^`, then `|`, then `&&`, then `||`. `&&` and `||` short-circuit. Comparisons require both sides to have the same type and produce `bool`.

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

### The two address spaces

QuinLang has two kinds of memory, and they are **separate types** so that an address from one cannot be used with the other.

`ptr` is a slot in the current frame, produced by `@`, and read or written with `load16` / `store16` / `memcpy` / `memset`:

```quin
let x: int;
let a: int[3];
let p: ptr;

p = @x;        // slot of x
p = @a[1];     // slot of a, plus 1
store16(p, 4321);
println(load16(p));
```

Because a frame address is a slot index, `memcpy` / `memset` counts are measured in **slots (16-bit words)**, not bytes:

```quin
let src: int[3];
let dst: int[3];

memcpy(@dst[0], @src[0], 3);   // 3 slots
memset(@dst[0], 0, 3);
```

`heapptr` is a byte offset into a 64 KiB heap, produced by `alloc` and accessed a word at a time:

```quin
let h: heapptr;
h = alloc(2);          // size in bytes, rounded up to a multiple of 2
heap_store(h, 1234);
println(heap_load(h)); // 1234
```

The allocator is a bump pointer with no `free`, and it runs out at 64 KiB.

`null` is a `heapptr` literal equal to heap address 0. Address 0 is reserved, so no allocation returns it. `heap_load(null)` or `heap_store(null, ...)` raises `Null pointer dereference`. `heapptr + int` and `heapptr - int` give a `heapptr`; `heapptr - heapptr` gives an `int` distance in bytes.

Crossing the two is a compile error rather than a silent misread:

```quin
load16(alloc(2));   // Argument type mismatch: expected ptr, got heapptr
heap_load(@x);      // Argument type mismatch: expected heapptr, got ptr
```

What is still on you: a `ptr` only makes sense inside the frame that produced it. Returning `@x` and dereferencing it in the caller reads whatever local occupies that slot, or faults with `Local index out of range` if the caller's frame is smaller.

### Inline bytecode

`vm_asm { ... }` drops to VM bytecode:

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

Names inside the block resolve against the scope at that point, including shadowed bindings. The block's stack effect is not checked, so an unbalanced block surfaces as `Unbalanced operand stack at RET` when the enclosing function returns. The supported instruction set is listed in [SYNTAX.md](SYNTAX.md#vm_asm-instruction-set).

---

## Compilation pipeline

1. **Lexing** (`compiler/lexer.py`, `tokens.py`) — source text to tokens, with `//` comments, decimal and `0x` hex literals, and 16-bit range checks.
2. **Parsing** (`compiler/parser.py`, `ast.py`) — recursive descent into an AST. Every node carries `line` / `col`.
3. **Include resolution** (`compiler/resolver.py`) — recursively parses included files, detects cycles, and merges everything into one `Program`.
4. **Semantic analysis** (`compiler/sema.py`) — scopes, name resolution, the entry-point contract, the array restrictions, return checking, and a type for every expression node.
5. **Code generation** (`compiler/codegen_vm.py`) — the typed AST to bytecode.
6. **Execution** (`runtime/vm.py`) — the interpreter runs the bytecode.

### What sema hands to codegen

`Context` is the whole interface between the front and back ends, and it is the single source of truth for what a name means:

- `node_type` — the type of every expression node.
- `binding` — the `Symbol` that each identifier, declaration, parameter, and assignment target resolves to.
- `frame_symbols` — every symbol a function declares, parameters first (the calling convention requires them to lead) and then declarations in source order.
- `asm_scope` — the names visible at each `vm_asm` block, since its body is raw text that no other pass resolves.

Codegen never walks scopes. It turns `frame_symbols` into slots and then looks up the `Symbol` sema already resolved each node to, so the two passes cannot disagree about which `x` an `x` refers to. Symbols are compared by identity, so shadowed and sibling-scope declarations get distinct storage for free.

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

The VM checks local indices, heap word bounds, operand-stack underflow, division and modulo by zero, and negative `memcpy` / `memset` counts. It does not check array bounds.

---

## Tests

```bash
python3 -m unittest discover -s tests -t .     # everything
python3 -m unittest tests.test_sema -v         # one module
```

| File | Covers |
| --- | --- |
| `tests/harness.py` | Compile/run helpers and QuinLang-flavored assertions |
| `tests/test_lexer.py` | Literals, comments, keywords, 16-bit range limits |
| `tests/test_parser.py` | Precedence, associativity, short-circuiting, syntax errors |
| `tests/test_sema.py` | Type rules, entry point, return checking, array restrictions |
| `tests/test_scoping.py` | Shadowing, sibling scopes, frame layout, `vm_asm` name resolution |
| `tests/test_pointers.py` | Frame vs heap address spaces, memory intrinsics, array helpers |
| `tests/test_runtime.py` | 16-bit arithmetic, control flow, calling convention, VM faults |
| `tests/test_resolver.py` | Include paths, cycles, diamonds, duplicate definitions |
| `tests/test_examples.py` | Every `examples/*.ql` against its golden output |

Tests are written as QuinLang source strings and asserted on their output or their error message, so they exercise the whole pipeline rather than one pass:

```python
self.assertPrints("fn main(): int { println(2 + 3 * 4); return 0; }", "14")
self.assertCompileError("fn main(): int { if (1) { } return 0; }", "If condition must be bool")
self.assertRuntimeError("fn main(): int { let z: int; println(1 / z); return 0; }", "Division by zero")
```

Golden files live in `tests/golden/`. After an intentional change to an example or to codegen, regenerate them and **read the diff** — a changed golden is either a fix or a regression, and only you can tell which:

```bash
python3 -m tests.update_golden
```

---

## Project layout

- `compiler/`
  - `lexer.py`, `tokens.py` — lexical analysis
  - `parser.py` — recursive-descent parser
  - `ast.py` — node definitions
  - `compiler_types.py` — `Type` objects, array-name parsing, helpers
  - `resolver.py` — `include` resolution and AST merging
  - `sema.py` — scopes, name resolution, and type checking
  - `builtins.py` — built-in function signatures
  - `bytecode.py` — opcodes and `Instruction`
  - `codegen_vm.py` — bytecode generation
  - `driver_vm.py` — CLI entry point
- `runtime/vm.py` — the QuinVM interpreter
- `std/` — `math.ql`; `io.ql` and `prelude.ql` are placeholders
- `examples/` — small QL programs, all covered by golden tests
- `tests/` — the test suite

---

## Limitations and gotchas

- Array indexing is bounds-checked at compile time for constant indices and at run time for computed indices; `array_push` / `array_pop` are **not** bounds-checked, so an in-frame overrun silently hits a neighboring local.
- A `ptr` does not outlive the frame it points into.
- The heap is a bump allocator with no `free`.
- `int` is the only numeric type: 16-bit, signed, wrapping.
- Comparing `str` values compares interned ids, so `==` and `!=` behave sensibly but `<` / `>` are meaningless (`"b" < "a"` is `true`).
- `main`'s return value never reaches the process exit code.
- `vm_asm` blocks are not checked for stack balance until run time.

Future directions: restricting relational operators to `int`, structs, a garbage collector, and filling out `std/`.

The goal is to keep the compiler and VM small enough to read in one sitting and see exactly how each language feature works end to end.
