# QuinLang (QL)

[![CI](https://github.com/HomseyFT/QuinLang/actions/workflows/ci.yml/badge.svg)](https://github.com/HomseyFT/QuinLang/actions/workflows/ci.yml)

QuinLang is a tiny, C-style language and compiler that I built to learn about parsing, type checking, and code generation from the ground up.

It compiles to bytecode for **QuinVM**, a stack machine written in Python. The whole toolchain is one `python3 -m` invocation with no third-party dependencies.

The language is intentionally small:

- `int`, `float`, `bool`, `str`, `ptr`, `heapptr`, and fixed-size stack arrays `int[N]`
- `struct` types: heap-allocated objects with reference semantics, including self-referential ones
- Functions with parameters, recursion, and `int` / `bool` / `str` / pointer / `void` returns
- `if` / `else`, `while`, `for`, `break` / `continue`, and bare `{ ... }` blocks
- Arithmetic (`+ - * / %`), comparisons, and short-circuit `&&` / `||`
- `print` / `println` statements for `int`, `str`, and `bool`
- Multi-file programs via `include`, plus a small `std/` library
- Frame-pointer intrinsics: `load16`, `store16`, `memcpy`, `memset`
- Heap intrinsics: `alloc`, `heap_load`, `heap_store`
- Array helpers: `array_push`, `array_pop`
- Constant-time-style helpers: `ct_eq`, `ct_select`
- `panic` to abort with a message, and `gc` to force a collection
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

The driver lexes, resolves `include`s, type-checks, compiles to bytecode, and runs it in-process — or loads an already-compiled [`.qlc`](#compiled-bytecode-files). Compile errors are reported as `Import error:`, `Semantic error:`, or `Codegen error:` with a `[line:col]` prefix. Runtime faults come out as `Runtime error:` and carry the same `[line:col]`, the function they happened in, and a backtrace — see [Runtime errors](#runtime-errors). Add `--debug` to run the program under the [debugger](#debugger) instead.

A larger tour of arrays, pointers, printing, and boolean logic:

```bash
python3 -m compiler.driver_vm examples/hello.ql
```

Other examples worth reading: `examples/control_flow.ql` (short-circuit operators), `examples/for_loops.ql` (`for`, `break` / `continue`, blocks), `examples/structs.ql` (structs, references, a linked list), `examples/gc.ql` (the collector at work), `examples/stdlib.ql` (a tour of the standard library), `examples/strings.ql` (building and inspecting strings), `examples/vm_arrays_push.ql` (`array_push`), `examples/floats.ql` (floats and `std/float.ql`), `examples/vm_asm_example.ql` (inline bytecode), `examples/ct_primitives.ql` (`ct_eq` / `ct_select`).

`main`'s return value becomes the process exit code, so a program can be tested from a shell:

```bash
python3 -m compiler.driver_vm prog.ql && echo "ok"
```

An exit status is 8 bits wide while `int` is 16-bit signed, so the low byte is what survives, exactly as in C: `return 256` exits 0 and `return -1` exits 255.

Because `return 256` exiting 0 looks exactly like success, the compiler warns when `main` returns a constant outside `0..255`:

```
Warning: [1:25] main returns 256, but a process exit code carries only the low
byte, so this exits 0. Return a value in 0..255 to say what you mean.
```

The check constant-folds, so `return 0 - 1`, `return 200 + 100`, and `return 32767 + 1` are all caught, reported as the value they actually produce. A return the compiler cannot evaluate is left alone. Warnings go to stderr, so piping stdout stays clean, and they change neither the exit code nor whether the program runs.

The tool's own failures use codes of their own, so a caller can tell them apart from the program's result:

| Exit code | Meaning |
| --- | --- |
| `0`..`255` | `main`'s return value, low byte |
| `2` | Compile error — nothing ran (also argparse's code for a bad command line) |
| `3` | Runtime error — the program faulted |

Nothing reserves `2` and `3` from a program, so `return 3` still exits 3. Errors always print to stderr and a clean run prints nothing there, which is the one signal that never collides.

### Running the tests

```bash
python3 -m unittest discover -s tests -t .
```

965 tests covering the lexer, parser, resolver, type checker, code generator, and VM. They run in about three seconds, so there's no reason not to run them on every change. See [Tests](#tests) for the layout.

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

`std/` ships six modules:

| Module | Provides |
| --- | --- |
| `std/math.ql` | `abs`, `min`, `max`, `clamp`, `sign`, `is_even`, `is_odd`, `pow`, `gcd`, `lcm`, `isqrt` |
| `std/bits.ql` | `bit_get` / `bit_set` / `bit_clear` / `bit_toggle`, `popcount`, `reverse_bits`, `leading_zeros`, `trailing_zeros`, `highest_bit`, `rotate_left` / `rotate_right`, `logical_shift_right` |
| `std/string.ql` | Searching, slicing, case conversion, trimming, parsing, and character predicates |
| `std/io.ql` | `newline`, `print_repeat`, `print_spaces`, `print_line`, `hex_digit`, `print_hex` / `println_hex`, `print_binary` / `println_binary`, `print_padded` |
| `std/list.ql` | `IntList`, a persistent singly linked list: `list_push`, `list_len`, `list_get`, `list_sum`, `list_reverse`, `list_contains`, and friends |
| `std/vec.ql` | `IntVec`, a growable int array on the heap: `vec_new`, `vec_push`, `vec_get`, `vec_set`, `vec_pop`, `vec_reverse`, and friends |
| `std/float.ql` | `fabs`, `fmin`, `fmax`, `fsign`, `floor`, `ceil`, `round`, `ftrunc`, `fpow`, `fclose` |
| `std/prelude.ql` | Includes the three function-only modules above, so one include brings in the common helpers |

The collection modules are not in the prelude, because each declares a struct type and a struct name is global once included. Include those by name when you want them.

Two constraints shaped the library. Arrays cannot be parameters or return types, so anything that crosses a function boundary is built from structs — a linked list, or a `heapptr` field wrapped in one. Strings, by contrast, are now first-class heap objects, which is what makes `std/string.ql` possible at all.

---

## Language overview

This is a quick tour; [SYNTAX.md](SYNTAX.md) is the reference.

### Types

- `int` — 16-bit **signed** integer. Arithmetic wraps (`32767 + 1` is `-32768`), and `/` truncates toward zero.
- `float` — 32-bit IEEE 754 single precision, about seven significant digits. The only type wider than a word: it occupies two slots wherever it is stored. `int` and `float` never mix implicitly. See [Floats](#floats).
- `bool` — `true` / `false`. Not interchangeable with `int`: conditions must be `bool`, and `true + 1` is a type error.
- `str` — a string: a heap object holding its length and its characters. Literals, concatenation, slicing and conversion all produce one, and the collector reclaims them. See [Strings](#strings).
- `ptr` — an address in the current frame, produced by `@`.
- `heapptr` — an address in the heap, produced by `alloc`.
- `void` — no value; only valid as a return type.
- `int[N]` — a fixed-size array of `N` ints in the current frame, for a literal `N > 0`.
- `fn(T, ...): R` — a function taking those parameter types and returning `R`. See [Functions as values](#functions-as-values).
- a `struct` name — a reference to a heap object. See [Structs](#structs).

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

### Functions as values

A function's name, anywhere other than in a call, is a value naming that function:

```quin
fn add(a: int, b: int): int { return a + b; }
fn mul(a: int, b: int): int { return a * b; }

fn apply(f: fn(int, int): int, x: int, y: int): int {
    return f(x, y);
}

fn main(): int {
    println(apply(add, 2, 3));           // 5

    let op: fn(int, int): int = mul;     // stored
    println(op(2, 3));                   // 6
    return 0;
}
```

The type is written the way the declaration is, minus the parameter names: `fn(int, int): int`. Omitting `: R` means `void`, so `fn(str)` and `fn(str): void` are the same type. Function types nest, so `fn(fn(int): int): void` is a function taking a function.

A function value is **one word holding an index into the program's function table** — not a heap address. It allocates nothing, the collector never traces one, and a `fn` field costs a struct exactly one slot. `std/list.ql` uses this for `list_map`, `list_filter` and `list_foreach`.

**There is no capture.** A function value says *which function*, and nothing more; there is no environment attached. Capturing would mean a value carrying state, which would have to live on the heap and be traced like any other object — a different feature, with a different cost.

Two things follow from `Call`'s callee being a name rather than an expression:

```quin
let f: fn(int, int): int = ops.apply;   // read the field into a variable first
println(f(6, 7));                       // then call through it
```

A call names a variable or a function, so `ops.apply(6, 7)` and `pick()(6, 7)` are not written directly. A variable shadows a function of the same name here as everywhere else, so a local named `f` is what `f()` calls.

Builtins are not function values. `println`, `alloc` and the rest are lowered to instructions at the call site and have no index to refer to, which the compiler says rather than calling them undeclared.

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

Indexing is **bounds-checked against the array itself**, not merely against the frame. A literal index outside the array is a compile error:

```
Semantic error: [3:6] Array index 7 out of bounds for length 3
```

and anything else is checked at run time by the `BOUNDS_CHECK` opcode:

```
Runtime error: [4:14] in main: Array index out of bounds: index=5, length=3
```

Both apply equally to a read, an assignment target, and `@a[i]`. An overrun therefore faults instead of quietly reading or writing a neighboring local.

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

These are bounds-checked exactly like indexing, since a push touches `arr[len]` and a pop touches `arr[len - 1]`. A literal length is a compile error:

```
Semantic error: [3:28] array_push at length 3 accesses index 3, out of bounds for length 3
Semantic error: [3:27] array_pop at length 0 accesses index -1, out of bounds for length 3
```

and a computed one faults at run time. The length is still yours to maintain — the check stops a mistake from reaching a neighboring local, it does not track the length for you.

### Structs

A `struct` declares a heap object type. Declarations sit at the top level, beside functions, and may appear in any order relative to the code that uses them:

```quin
struct Point {
    x: int,
    y: int,
}

fn main(): int {
    let p: Point = Point { x: 3, y: 4 };
    println(p.x);      // 3
    p.y = 10;
    println(p.y);      // 10
    return 0;
}
```

A struct value is a **reference**, so assigning one does not copy the object:

```quin
let q: Point = p;
q.x = 99;
println(p.x);          // 99 — p and q are the same object
```

That is also why a function can modify its caller's object, and why `==` compares identity rather than field values.

A field may be another struct, including the struct being declared. That is what makes linked structures work:

```quin
struct Node {
    value: int,
    next: Node,
}

let head: Node = null;
for (let i = 1; i < 4; i = i + 1) {
    head = Node { value: i, next: head };
}
println(head.value);        // 3
println(head.next.value);   // 2
```

Field types are resolved in a second pass over the declarations, so a struct may name itself, name a struct declared later, or name one from an included file.

An uninitialized struct variable is `null`, and reaching through a null reference is a runtime error rather than a silent misread:

```quin
let n: Node;
println(n == null);    // true
println(n.value);      // Runtime error: [4:15] in main: Null pointer dereference
```

Rules worth knowing: a literal must give every field exactly once, in any order; fields are read and written but a struct has no value form for `print`; relational operators (`<`, `>`, …) do not apply to references; and a struct cannot have array-typed or `void` fields.

### Sum types

A struct says a value has *all* of these fields. An enum says it is *one* of these shapes:

```quin
enum Result {
    Ok(int),
    DivideByZero,
    NotADigit(int),
}

fn checked_div(a: int, b: int): Result {
    if (b == 0) { return Result::DivideByZero; }
    return Result::Ok(a / b);
}

fn main(): int {
    match (checked_div(10, 0)) {
        Result::Ok(value)    => { println(value); }
        Result::DivideByZero => { println("divided by zero"); }
        Result::NotADigit(c) => { println(c); }
    }
    return 0;
}
```

This is what lets a library report a failure without stopping the program. `panic` is still there for a broken invariant, but "the caller gave me a zero" is not that — it is an outcome, and now it can be returned as one. Because the failure is in the type, the caller cannot read the answer without first saying what happens when there isn't one.

- Payloads are **positional**: `Ok(int)` declares one, `Result::Ok(5)` builds it, `Result::Ok(v)` binds it.
- A variant carrying nothing is written bare: `Result::DivideByZero`, never `Result::DivideByZero()`. The declaration refuses `A()` for the same reason — one value, one spelling.
- **A variant is always written `Enum::Variant`.** Only the declaration uses the short name, where the enum is already named by the line above it. Qualifying makes a variant impossible to confuse with a variable, a function, or another enum's variant of the same name, and it is why two enums may both declare `Ok` — and why `std/` could declare enums without claiming names for every program that includes it.
- The subject of a match is parenthesised, as an `if` condition is. Not only for consistency: `match r {` is ambiguous, because an identifier followed by a brace is how a struct literal begins, so the subject would swallow the arms.
- A match must be exhaustive. `_` covers the rest, and warns if there is no rest to cover — that arm is the one that would silently absorb a variant added later.

A short name on its own is a compile error that names the spelling to use, so the fix is always in the message:

```
Semantic error: [3:22] 'Ok' is a variant name; write 'Result::Ok'
```

```
Semantic error: [7:5] match on 'Result' does not cover: DivideByZero, NotADigit
Warning: [9:9] '_' covers no remaining variant of 'Result'
```

An enum reference is nullable, so covering every variant is not a promise that the value *is* one of them. Matching a null subject faults, exactly as reading a field of a null struct does.

#### What it cost the runtime

Almost nothing, because of a coincidence worth naming. Every heap object already carries a type id in its header — the collector reads it to find which of the object's words are references. A variant is a struct at run time: same header, same layout, an entry in the same table. So **the tag is the type id**, `TAG_OF` reads the field the collector was already reading, and the collector itself needed no changes at all.

A match lowers to `TAG_OF` and a compare-and-jump chain, patched the way an `if` is. There is no indexed-jump opcode: an enum has a handful of variants, so a chain costs a couple of compares and keeps the instruction set smaller.

A variant carrying nothing is a constant, so it is **interned**, not allocated: one immortal instance per variant, materialised at startup and rooted for the whole run, exactly as string literals are. A list of a thousand `Cons` cells shares one `Nil`, and an enum of bare variants allocates nothing at all no matter how often it is used.

### Floats

A `float` is 32-bit IEEE 754 single precision. It is the only type wider than a machine word, so it occupies **two consecutive slots** wherever it is stored — a frame local, a parameter, a struct field.

```quin
let x: float = 1.5;
let y: float = 0.25;

println(x + y);        // 1.75
println(x / y);        // 6.0
println(x > y);        // true
println(1.0 / 3.0);    // 0.33333334 -- seven digits, not seventeen
```

A literal needs digits on both sides of the point: `1.5` and `3.0`, never `1.` or `.5`. There is no exponent notation, and `1e5` is a lex error rather than silently lexing as `1` followed by the identifier `e5`.

**`int` and `float` never mix.** There is no implicit widening, so `int_to_float` and `float_to_int` are the only bridge:

```quin
let n: int = 7;
let x: float = 1.5;

println(x + n);                   // Semantic error: Cannot mix int and float
println(x + int_to_float(n));     // 8.5
println(float_to_int(3.75));      // 3 -- truncates toward zero, like integer /
```

A silent widening would make `total / count` mean different things depending on a declaration somewhere else in the file, so the conversion is written where it happens.

Two arithmetic mistakes fault rather than producing a value that spreads quietly:

```
Runtime error: [3:17] in main: Float division by zero
Runtime error: [3:15] in main: Float overflow: 9.000000360735796e+40 does not fit in a 32-bit float
```

Integer overflow wraps and is documented as wrapping, but a float that became infinity would make every later comparison lie, and there is no way to express that in a result.

Three places refuse a float because a pointer or an instruction there addresses exactly one slot, and would silently work on half the value:

| | Why |
| --- | --- |
| `float[N]` | Array indexing counts one element per slot |
| `@x` on a float | A `ptr` names one slot; `load16` would read half a value |
| `vm_asm { load_local x; }` | The `vm_asm` instruction set moves one slot at a time |

Values that only differ in their last digits are what floats are for, so exact equality is usually the wrong test. `std/float.ql` provides `fclose`:

```quin
include "std/float.ql";

let acc: float = 0.0;
for (let i = 0; i < 10; i = i + 1) { acc = acc + 0.1; }

println(acc);                        // 1.0000001
println(acc == 1.0);                 // false
println(fclose(acc, 1.0, 0.001));    // true
```

Printing shows the shortest decimal that reads back as the same 32-bit value, always with a point so `3.0` cannot be mistaken for an int. `float_to_str` produces the same text.

### Strings

A string is a heap object: a header carrying its length, then its characters, one byte each. A `str` value is that object's address, so strings are allocated, moved and reclaimed exactly like structs.

```quin
let name: str = "Ada";
let greeting: str = "hello, " + name + "!";
println(str_len(greeting));           // 12
println(str_slice(greeting, 7, 10));  // Ada
println(int_to_str(42) + "!");        // 42!
```

- `+` on two strings builds a new one.
- `str_len`, `str_char_at`, `str_slice`, `int_to_str` and `char_to_str` are builtins; everything else lives in `std/string.ql`.
- A character is a byte, so `str_char_at` gives a code in `0..255` and `char_to_str` turns one back. There is no `char` type.
- Comparison reads the characters, so `==` and the ordering operators work on built strings and literals alike.

Literals are interned at compile time and materialised into the heap when the program starts. Their addresses are permanent roots — a literal is named by the bytecode rather than by any variable, so nothing else would keep it alive.

Everything else is ordinary garbage:

```quin
// 20000 strings through a 64 KiB heap, because they are collected
for (let i = 0; i < 20000; i = i + 1) {
    let s: str = int_to_str(i);
}
```

A string holds characters and never references, so the collector keeps one alive without tracing into it — the same treatment a block from `alloc` gets.

Unlike the other heap types, **there is no null string**. An uninitialised `str` is the empty string, matching `int` starting at zero, so no string operation needs a null check and `null` is not assignable to a `str`.

String literals support the escapes `\n`, `\t`, `\r`, `\0`, `\\` and `\"`. An unrecognised escape is a lex error rather than a silently preserved backslash.

Because a character is a byte, a literal may only contain characters that fit in one — `U+0000` to `U+00FF`. Anything above that is rejected where it is written:

```
Syntax error in prog.ql:1:29: Character U+2192 does not fit in a byte; a str holds one byte per character
```

Source files are otherwise UTF-8, so this only constrains what goes inside quotes.

### Input

A program can read its input and its arguments, which is the difference between a language for computing something and a language for processing something.

```quin
include "std/input.ql";

fn main(): int {
    while (true) {
        match (next_line()) {
            Input::Line(text) => { println(text); }
            Input::End        => { break; }
        }
    }
    return 0;
}
```

The primitive underneath is `read_line()`, and it keeps the line's terminator. That is the whole design: a blank line is `"\n"` and only end of input is `""`, so the two can never be confused. Stripping the newline inside `read_line` would make the last line of a file indistinguishable from the end of it — and the symptom is not a crash but a loop that stops early or never stops at all.

`std/input.ql` turns that convention into an `enum`, which is the version worth writing programs against: a rule you have to remember becomes a variant you have to account for. It is not in the prelude, because it declares a type and a type name is global once included — the same reason `std/list.ql` and `std/vec.ql` are left out.

Input is **bytes**, consistent with a `str` holding one byte per character: a UTF-8 character arrives as several, and one too wide for a byte is a runtime fault rather than a silent mangling.

Arguments come through `argc()` and `argv(i)`. `argc()` counts what the host supplied and may be zero, so a program indexes from 0 rather than assuming `argv(0)` exists — the driver puts the program path there as C does, but an embedded VM supplies whatever it has. Everything after the source file belongs to the program:

```bash
python3 -m compiler.driver_vm prog.ql --verbose input.txt
```

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

Memory is reclaimed by a garbage collector, so dropping a reference makes its object reusable. See [Garbage collection](#garbage-collection).

`null` is a reference literal equal to heap address 0, and initializes any `heapptr` or struct type. Address 0 is reserved, so no allocation returns it. `heap_load(null)` or `heap_store(null, ...)` raises `Null pointer dereference`. `heapptr + int` and `heapptr - int` give a `heapptr`.

`heapptr - heapptr` is deliberately **not** an operation. It was the only expression that yielded a reference's numeric value as an `int`, which would let a program stash an address inside an untyped block where a collector does not look and reconstruct it later. Removing it is what lets untyped blocks be treated as containing no references.

Every heap allocation carries a two-word header just below the address the program holds: the object's kind plus the collector's mark bit, and either a struct type id or a byte size. The collector reads it to recover an object's size and which of its words are references, and it makes the heap parseable end to end.

Crossing the two is a compile error rather than a silent misread:

```quin
load16(alloc(2));   // Argument type mismatch: expected ptr, got heapptr
heap_load(@x);      // Argument type mismatch: expected heapptr, got ptr
```

What is still on you: a `ptr` only makes sense inside the frame that produced it. Returning `@x` and dereferencing it in the caller reads whatever local occupies that slot, or faults with `Local index out of range` if the caller's frame is smaller.

### Garbage collection

The heap is collected by a precise, sliding **mark-compact** collector. After marking, surviving objects are slid down into the space the dead vacated and every reference is rewritten to follow them, so the free memory is always one contiguous run above the allocation pointer.

That is what makes allocation a bump pointer and nothing more: there is no free list, no first-fit search, and no fragmentation. A program can always use every free byte, however scattered the garbage was.

```quin
fn make_garbage(): void {
    let junk: Node = Node { value: 1, next: null };
}

fn main(): int {
    // 40000 nodes through a heap that holds about 8000. Nothing retains
    // them, so the program completes rather than running out of memory.
    for (let i = 0; i < 40000; i = i + 1) {
        make_garbage();
    }
    return 0;
}
```

Collection runs when an allocation cannot be satisfied; the allocation is then retried once, and only fails if the collection did not free enough. `gc()` forces a cycle at a point of your choosing.

**Finding the roots.** A collector has to know every reference the program can still reach. Two of those places are easy, and one is not:

- Each frame's locals, via the stack map the compiler emits (`ref_slots`). Suspended callers count too, so a frame that is waiting on a call still protects its objects.
- The operand stack, which is the awkward one. Building `Node { value: 1, next: Node { ... } }` leaves the outer object on the operand stack and in no variable at all while the inner one allocates. A collector that scanned only locals would free an object that is about to be used.

The operand stack is a flat list of words with no types attached, and guessing is not an option: heap addresses and `int` both span the full 0–65535 range, so no value can be recognised as a pointer by looking at it. The VM therefore tracks a reference flag beside every operand-stack entry, set as each value is pushed — `ALLOC` pushes a reference, `PUSH_INT` does not, `DUP` copies the flag, and a field load consults the object's header to see whether that field is a reference.

**Tracing.** From each root the collector marks the object, and for a struct follows the reference fields named by its `ref_offsets`. Blocks from `alloc` are kept alive but never traced through: nothing in the language can place a reference inside one, which is precisely what dropping `heapptr - heapptr` and address-of on references bought. Cycles are collected, since reachability is what matters rather than a count.

A reference may point into the middle of a block, because `heapptr + int` is allowed. The collector resolves such a pointer to the block containing it, and that block stays alive.

**Moving.** Once marking is done the collector makes three more passes over the heap, which it can walk in address order because every object records its own size:

1. **Plan** — walk the live objects and work out where each will sit once the gaps are closed, building a map from old address to new. The map is an ordinary Python dict rather than forwarding words written into the heap; a collector living inside the memory it manages could not afford that, and this one can.
2. **Update** — rewrite every reference through the map, in all four places marking visits: the current frame, suspended frames, the operand stack, and reference fields inside live objects. A reference that points into the *middle* of an object keeps its offset, since `heapptr + int` is allowed. This happens before anything moves, so by the time objects are copied their contents are already correct.
3. **Move** — copy each survivor down. Blocks are processed in ascending order and only ever move downward, so a destination always lies below every block still to be copied and cannot overwrite one.

The reclaimed space is then zeroed. Sliding an object down leaves its old bytes intact, so a reference the collector failed to update would still read a perfectly good copy of the object and return the right answer — a bug that only appears much later, when that memory is handed out again. Wiping it turns that into an immediate null dereference.

**Releasing a scope.** When a scope ends, the compiler stores null into the reference slots it declared, so leaving a scope stops its variables rooting what they named:

```quin
for (let i = 0; i < 1000; i = i + 1) {
    let big: Wide = Wide { ... };
}   // big's slot is cleared here, on every iteration
```

Without this the slot keeps its last value until the function returns, so a loop leaves one object — possibly a large one — alive for the rest of the function. `break` and `continue` release the scopes they jump out of too.

This costs two instructions per reference slot per scope exit, and nothing at all for a scope that declares no references, which is most of them. It needs no VM support: the collector already ignores a slot holding null.

Clearing a slot removes one root, not the object. Anything still reachable another way is untouched:

```quin
let keep: Node = null;
for (let i = 0; i < 5; i = i + 1) {
    let a: Node = Node { value: i, next: null };
    keep = a;      // survives; 'a' going out of scope changes nothing
}
```

**Why moving is safe here.** Every reference the program can reach is known exactly: the compiler's stack maps say which frame slots hold one, and the VM tags the operand stack as it pushes. Just as importantly, no QuinLang expression can turn a reference into an `int` — neither `heapptr - heapptr` nor address-of on a reference exists — so a program cannot be holding a copy of an address that the collector does not know to update. Those two restrictions were added for exactly this reason.

Two things worth knowing:

- The stack map is per function, not per instruction, so a variable that is still in scope keeps its object alive even if the code will never read it again. Scope boundaries are handled — see below — but a dead variable in the function's own top-level scope survives until the function returns. Closing that needs real liveness analysis.

  The map can be per function precisely because locals start at zero and address 0 is null, so a slot read before its first assignment is simply skipped. Releasing a slot is the same trick applied at the other end.
- Object addresses are stable between collections but not across one. Nothing in the language can observe this, since a reference can never be converted to an integer.

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

Names inside the block resolve against the scope at that point, including shadowed bindings. The supported instruction set is listed in [SYNTAX.md](SYNTAX.md#vm_asm-instruction-set).

A block is straight-line — the instruction set has no jumps — so its stack effect is the sum of its instructions and is checked at compile time. A block must end at the depth it started, and may never pop below it:

```
Codegen error: [2:5] vm_asm block leaves 1 value(s) on the operand stack; it must end balanced
Codegen error: [1:30] vm_asm 'add' needs 2 value(s) on the operand stack but the block has 1
```

Both halves of each instruction's effect matter, not just the net: `add` nets −1 but needs two operands, so a block holding one value would otherwise reach past its own start into the enclosing frame.

---

## Runtime errors

A fault names the position, the function, and how the program got there:

```
Runtime error: [3:14] in depth3: Division by zero
  at depth3 (line 3)
  at depth2 (line 5)
  at main   (line 7)
```

A program with a single frame prints no trace, since the header already named the only function. When the frames span more than one file — which any call into `std/` does — each line names its file instead, because a bare line number is ambiguous once a program is more than one file:

```
Runtime error: [30:14] in clamp (std/math.ql): clamp called with lo greater than hi
  at clamp (std/math.ql:30)
  at main  (prog.ql:3)
```

The position comes from a **source map** built during code generation: a sorted list of `pc -> (line, col)` markers, binary-searched when something goes wrong. It is stored beside the bytecode rather than on each `Instruction`, so the interpreter loop and the instruction itself are exactly the size they were, and nothing reads the table until a fault or a debugger asks for it. Markers, not one entry per instruction — a run of instructions lowered from one expression costs a single entry.

Codegen attributes each instruction to the **innermost** node that produced it. It notes a node's position on the way in and restores the enclosing one on the way out, so `1 / z` reports the `/` rather than the statement containing it.

Two other tables are built at the same time and for the same reason:

| Table | Holds |
| --- | --- |
| `FunctionInfo.locals_` | Every slot in a frame by name, with its type, its width in slots, and whether it is a parameter |
| `FunctionInfo.source_file` | Which file declared the function, so a backtrace can say |

The slot table is what the debugger's `print x` reads; building it alongside the source map cost one pass rather than two.

`CodeGenVM.generate()` returns these as a named `CompiledProgram` rather than a tuple: the tables are independent of one another and there are now five, which is past the point where unpacking them positionally at every call site pays for itself.

---

## Debugger

`--debug` runs a program under an interactive debugger instead of straight through:

```bash
python3 -m compiler.driver_vm --debug demo.ql
```

It stops before the first statement and prompts. The commands are the ones every debugger already has, because a familiar name needs no documentation:

| | |
| --- | --- |
| `break <fn>` / `break <line>` / `break <file>:<line>` | set a breakpoint |
| `delete [id]`, `enable <id>`, `disable <id>`, `breakpoints` | manage them |
| `continue` `c` | run to the next breakpoint |
| `step` `s` / `next` `n` | one line, entering calls / stepping over them |
| `finish` `f` | run until the selected frame returns |
| `backtrace` `bt`, `frame <n>` | the call stack, and which frame to read |
| `print <name>` `p`, `locals` | show one variable, or all of them |
| `list [n]` `l` | source around the current line |
| `help` `h`, `quit` `q` | |

An empty line repeats the last command, so stepping is one keystroke.

```
QuinLang debugger. 'help' for commands.
Stopped at main at demo.ql:9
    9  let p: Point = Point{x: 3, y: 4};
(qdb) break scale
Breakpoint 1 at scale (demo.ql:4)
(qdb) continue
Breakpoint 1, scale at demo.ql:4
    4  let sum: int = p.x + p.y;
(qdb) backtrace
-> #0 scale at demo.ql:4
   #1 main  at demo.ql:14
(qdb) locals
  p    param  Point = Point { x: 3, y: 4 }
  k    param  int = 2
  sum  local  int = 0
(qdb) finish
main at demo.ql:14
   14  total = total + scale(p, k);
(qdb) next
main at demo.ql:15
   15  i = i + 1;
(qdb) print total
total: int = 14
```

Values are shown as the language defines them, not as raw words: a negative `int` is signed, a `float` is read from both of its slots, a `str` and a `struct` are followed into the heap, and an array prints its elements. A `struct` expands its fields by name — which is why `StructLayout` carries them — and stops at a fixed depth so a cyclic structure terminates.

The depth cap is a property of the terminal, not of the debugger. `runtime/debugger.py` describes a value once — a summary, a type, and where its children are — and each front end renders it: a terminal has to fit the whole thing on one line, while an editor hands the user an expander and reads one level per click. That is why a cyclic list can be walked forever in an IDE and stops at three levels here.

### Program output

The VM does not print. It writes to a `ProgramIO`, which defaults to the console so a plain run is unchanged:

```python
vm = QuinVM(program.code, program.functions, program.strings,
            program.structs, program.source_map, io=CaptureIO())
```

This matters as soon as anything else owns stdout. A debug adapter speaks its protocol there, so a single `println` from the debugged program would corrupt the stream; an editor embedding the VM has no process stdout to write to at all. Six opcodes route through it — `PRINT`/`PRINTLN` for int, str and float — and nothing else in the interpreter writes.

Only the *program's* output goes through it. Compile diagnostics, warnings and runtime faults are the tool talking, not the program: they travel as exceptions and reach stderr from the driver, so redirecting a program's output never swallows the reason it stopped.

### Editors: the debug adapter

`dap/` is a [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/) server, so VS Code, Neovim, Emacs and Zed can drive the same debugger from one implementation:

```bash
python3 -m dap                 # stdio; the client spawns this
python3 -m dap --server 4711   # TCP on 127.0.0.1, for an editor that connects
```

Breakpoints by line and by function, stepping, pause, the call stack, locals, struct and array expansion, hover and watch — all of it is the same `runtime/debugger.py` the terminal client drives, so the two front ends cannot disagree about what a variable looks like.

`docs/editors.md` has the setup for each editor. VS Code needs no build step: `docs/vscode/` is a complete extension, and linking it into `~/.vscode/extensions/` is the whole install. `docs/nvim-dap.lua` is a drop-in config for Neovim.

Two decisions in it are worth naming.

**Compiling and starting are different moments.** `launch` compiles; `configurationDone` starts. Clients disagree about which of those they send first, so whichever arrives second is the one that starts the program. Starting on `launch` is the common shortcut and the reason adapters race their own breakpoint configuration.

**The adapter's stdout is carrying the protocol**, which is why `ProgramIO` exists. A program that printed directly to it would corrupt the stream — so program output travels as `output` events instead, and the same split resolves the problem the terminal debugger has, where the REPL and a reading program compete for one terminal. Here they are simply different channels.

The one thing DAP cannot express is reading input: it has no standard reverse request for it, so a program run under the adapter sees an empty stdin. That reports as end of input rather than as a blank line, so a reading program terminates instead of misreading.

### How it hooks in

`QuinVM` offers exactly one control point: a `hook` called with the VM before each instruction. Everything else is built on it — a breakpoint is a pc the hook recognises, and a step is a comparison against the source line and call depth the step began at.

The loop reads `hook` **once into a local** before it starts, not per instruction. Read per instruction it costs a measurable ~3%; hoisted it is under 1%, which is inside the run-to-run noise. The trade is that a hook must be attached before `run_main` and cannot be swapped mid-run, which is all a debugger needs. `tests/test_debugger.py` pins that, so anyone who moves the read back into the loop gets a failing test rather than a silent 3%.

The split is deliberate: `runtime/debugger.py` holds the state machine and does no I/O, `compiler/debug.py` holds the terminal session. That is what lets the tests drive the whole thing with a list of commands instead of a terminal.

A front end **must** say how to resume before returning from `on_stop`; forgetting raises `ResumeNotChosen` rather than defaulting to continue. Defaulting reads as harmless and is not — a `step` that quietly became a `continue` looks like a breakpoint that failed to fire, and the further the front end sits from the VM, the harder that is to see.

A fault stops one last time before it propagates. The VM does not unwind its own frames when it raises, so the entire call stack is still there to inspect at the moment the information is most wanted:

```
(qdb) continue
Runtime error: [3:14] in risky: Division by zero
  at risky (line 3)
  at main  (line 7)
The program cannot continue; inspect and then 'quit'.
(qdb) print z
z: int = 0
```

Quitting a faulted session still exits `3`: leaving the debugger does not unmake the fault.

---

## Compilation pipeline

1. **Lexing** (`compiler/lexer.py`, `tokens.py`) — source text to tokens, with `//` comments, decimal and `0x` hex literals, and 16-bit range checks.
2. **Parsing** (`compiler/parser.py`, `ast.py`) — recursive descent into an AST. Every node carries `line` / `col`.
3. **Include resolution** (`compiler/resolver.py`) — recursively parses included files and merges everything into one `Program`. Each file is resolved once, keyed by absolute path, so including the same file twice is harmless and a cycle simply terminates rather than being reported as an error.
4. **Semantic analysis** (`compiler/sema.py`) — struct layouts, scopes, name resolution, the entry-point contract, the array restrictions, return checking, and a type for every expression node.
5. **Code generation** (`compiler/codegen_vm.py`) — the typed AST to bytecode.
6. **Execution** (`runtime/vm.py`) — the interpreter runs the bytecode and collects the heap.

### What sema hands to codegen

`Context` is the whole interface between the front and back ends, and it is the single source of truth for what a name means:

- `node_type` — the type of every expression node.
- `binding` — the `Symbol` that each identifier, declaration, parameter, and assignment target resolves to.
- `frame_symbols` — every symbol a function declares, parameters first (the calling convention requires them to lead) and then declarations in source order.
- `asm_scope` — the names visible at each `vm_asm` block, since its body is raw text that no other pass resolves.
- `structs` — each struct's field layout and its heap type id.

Two of these outlive the compiler. Codegen turns `structs` into a table the VM carries, giving each object's size and the word offsets of its reference fields; and it turns `frame_symbols` into a per-function **stack map** of which local slots hold references. Together they are what the collector uses to find its roots and trace through the heap.

The stack map can be per-function rather than per-instruction because locals start at zero and address 0 is reserved for null, so a slot read before its first assignment is simply skipped — no liveness analysis required.

Codegen never walks scopes. It turns `frame_symbols` into slots and then looks up the `Symbol` sema already resolved each node to, so the two passes cannot disagree about which `x` an `x` refers to. Symbols are compared by identity, so shadowed and sibling-scope declarations get distinct storage for free.

### Opcode numbering

An opcode's number is part of the instruction set, not an implementation detail: it is what a serialised program would be made of, and what an old file means when a newer compiler reads it. So they are written out explicitly rather than left to `enum.auto()`, which numbers by position — under `auto()`, inserting an opcode anywhere but the end silently renumbers every one after it, and a file written before that insert would still load, as a *different program*.

The rules, enforced by `tests/test_opcodes.py`:

- Add new opcodes with the next free number. Adding is additive and safe.
- Never change a number that already exists.
- Never reuse the number of one you remove — leave the hole and record it in `RETIRED`, so an old file fails to load rather than decoding into whatever took its place.
- `0` is not an opcode, so a format can use it as a terminator or an absent-marker.

The test pins every name to its number and fails on a renumber, a reorder, a reuse, or a return to `auto()`. Adding an opcode asks you to record it, which is the moment to notice the format grew.

### Compiled bytecode files

`-o` writes the compiled program to a `.qlc` instead of running it, and a `.qlc` runs wherever a `.ql` does:

```bash
python3 -m compiler.driver_vm -o prog.qlc prog.ql   # compile
python3 -m compiler.driver_vm prog.qlc              # run, no source needed
python3 -m compiler.driver_vm -o prog.qlc --strip prog.ql
```

Flags go **before** the source file: everything after it is the program's own `argv`, which is what lets a program take a `--flag` of its own.

Which file you handed it is decided by the file's first bytes, not its name. What a file *is* is not the caller's to guess from a suffix, and a `.qlc` renamed to `.ql` would otherwise reach the lexer and be reported as a syntax error in binary data.

**A `.qlc` is a build artifact, not an archive format.** The header stamps a format version and the loader refuses any other, the way a `.pyc` refuses a foreign magic. That refusal is what keeps the tables underneath free to move: promise that an old file still loads and the opcode numbering, the struct encoding and the debug tables all become frozen public surface, with a migration path owed on every change. Refusing costs one line telling you to recompile — and loosening that later is easy, where tightening it would not be.

`--strip` leaves out what only a reader of source needs: the source map, the local-name tables, and the file each function came from. It cuts a file to roughly a third, and it costs more than the debugger — a runtime error keeps its message but loses its `[line:col]` and the line numbers in its backtrace:

```
Runtime error: [2:14] in risky: Division by zero      Runtime error: in risky: Division by zero
  at risky (line 2)                                     at risky
  at main  (line 5)                                     at main
```

So it is opt-in. Function names stay either way; a backtrace naming no functions is not worth the bytes. `--debug` on a stripped program is refused rather than started, because stepping through code with no line numbers is not debugging.

### QuinVM bytecode

`compiler/bytecode.py` defines the `OpCode` enum and `Instruction`; `runtime/vm.py` implements the interpreter. Values are 16-bit words held as ints masked to `0..0xFFFF`, sign-extended by anything that cares. The one exception is a `float`, which is a single operand-stack entry holding its full 32-bit pattern — see the calling convention below.

- Stack and locals: `PUSH_INT`, `LOAD_LOCAL`, `STORE_LOCAL`, `LOAD_LOCAL_IDX`, `STORE_LOCAL_IDX`, `BOUNDS_CHECK`, `POP`, `DUP`, `SWAP`
- Arithmetic: `ADD`, `SUB`, `MUL`, `DIV`, `MOD`, `NEG`
- Bitwise: `AND`, `OR`, `XOR`, `SHL`, `SHR`, `BITNOT`
- Comparisons: `CMP_EQ`, `CMP_NE`, `CMP_LT`, `CMP_LE`, `CMP_GT`, `CMP_GE`
- Logic and control flow: `NOT`, `JMP`, `JZ`, `JNZ`
- Calls: `CALL`, `RET`
- Frame-relative pointers: `LOAD_INDIRECT`, `STORE_INDIRECT`, `MEMCPY_LOCALS`, `MEMSET_LOCALS`
- Heap: `ALLOC`, `ALLOC_TYPED`, `HEAP_LOAD`, `HEAP_STORE`, `HEAP_LOAD_FIELD`, `HEAP_STORE_FIELD`, `HEAP_LOAD_FIELD_F`, `HEAP_STORE_FIELD_F`, `GC`, `PANIC`
- Strings: `LOAD_STR`, `STR_CMP`, `STR_LEN`, `STR_CHAR_AT`, `STR_CONCAT`, `STR_SLICE`, `STR_FROM_INT`, `STR_FROM_CHAR`, `STR_FROM_FLOAT`
- Floats: `PUSH_FLOAT`, `LOAD_LOCAL_F`, `STORE_LOCAL_F`, `FADD`, `FSUB`, `FMUL`, `FDIV`, `FNEG`, `FCMP`, `F_FROM_INT`, `F_TO_INT`
- I/O: `PRINT_INT`, `PRINT_STR`, `PRINTLN_INT`, `PRINTLN_STR`, `PRINT_FLOAT`, `PRINTLN_FLOAT`

Calling convention: arguments are pushed left to right and consumed by `CALL` into the callee's leading locals. **Every** function pushes exactly one return value — void functions and void builtins push a dummy `0` that the caller pops — so `RET` is uniform. Each frame records the operand-stack height at entry, and `RET` verifies the balance, which turns a codegen bug into an immediate `Unbalanced operand stack at RET` instead of silent corruption.

A `float` is where the one-word-per-value rule needed a decision. It is **two slots** in storage but **one entry** on the operand stack, carrying the whole 32-bit pattern. That split is deliberate: it keeps `POP`, `DUP`, `SWAP` and the `RET` balance check counting values rather than words, so none of them had to learn about width. `LOAD_LOCAL_F` and `STORE_LOCAL_F` are the only places the value is split and rejoined, and `FunctionInfo.param_words` tells `CALL` how far to advance for each argument, since a float argument arrives as one entry and fills two slots. The collector is unaffected either way — a float is never a reference, so both halves are simply skipped.

The VM checks local indices, heap word bounds, operand-stack underflow, division and modulo by zero, negative `memcpy` / `memset` counts, null dereferences, and — via `BOUNDS_CHECK` — array indices against the array's own length.

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
| `tests/test_structs.py` | Struct declaration, literals, fields, references, null, object layout |
| `tests/test_gc.py` | What the collector reclaims, what it must not, and operand-stack tagging |
| `tests/test_stdlib.py` | Every standard library function, its edge cases, and `panic` |
| `tests/test_strings.py` | Escapes, string construction, the heap representation, and collection |
| `tests/test_floats.py` | Float storage width, the calling convention, struct fields, precision, and `std/float.ql` |
| `tests/test_debug_info.py` | The source map, fault locations, backtraces, and the per-frame slot-name table |
| `tests/test_debugger.py` | Breakpoint resolution, each step mode, value inspection, post-mortem, and the command front end |
| `tests/test_driver.py` | The CLI as a real process: exit codes, warnings, error reporting |
| `tests/test_examples.py` | Every `examples/*.ql` against its golden output |
| `tests/test_enums.py` | Enum declaration, variant construction, match, exhaustiveness, interning, and tracing |
| `tests/test_program_io.py` | That program output goes where the caller says, and never to a stdout it does not own |
| `tests/test_input.py` | `read_line`, `argc`/`argv`, and `std/input.ql` — mostly the line/end-of-input boundary |
| `tests/test_dap_protocol.py` | DAP framing: byte-counted lengths, split reads, and malformed streams |
| `tests/test_dap_session.py` | The adapter's lifecycle, output events, exit codes, and both client orderings |
| `tests/test_opcodes.py` | That opcode numbers never change meaning, since a serialised program is made of them |
| `tests/test_no_dependencies.py` | That nothing outside the standard library is imported, and that the sources still parse as Python 3.10 |

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

### Continuous integration

`.github/workflows/ci.yml` runs the suite on every push to `master` and every pull request, across six jobs:

| | |
| --- | --- |
| Ubuntu | Python 3.10, 3.11, 3.12, 3.13 |
| Windows | Python 3.12 |
| macOS | Python 3.12 |

3.10 is the floor because `compiler/ast.py` uses `dataclasses.field(kw_only=True)`. Windows earns a job because `process_exit_code` exists specifically for it: POSIX truncates an exit status to its low byte anyway, so on Linux the masking is invisible and only a real Windows run exercises the difference.

There is no dependency-install step, because there are no dependencies. `tests/test_no_dependencies.py` fails the build if an import outside the standard library ever appears, so that stays true by construction rather than by good intentions.

`.github/workflows/notify-ide.yml` tells the `QuinLang-Text-Editor` repo about a new compiler. It waits on a green CI run instead of firing on the push directly, so a commit that breaks the compiler is never handed to the editor. That costs the path filter it used to have — `workflow_run` has no `paths` option — so a docs-only push now syncs too. That is the cheaper mistake.

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
  - `debug.py` — the interactive debugger session
- `runtime/`
  - `vm.py` — the QuinVM interpreter
  - `debugger.py` — breakpoints, stepping, and inspection
  - `program_io.py` — where a program's output goes
- `dap/` — a Debug Adapter Protocol server, so editors can drive the debugger
  - `protocol.py` — message framing
  - `session.py` — lifecycle, request dispatch, and events
  - `__main__.py` — entry point and transport selection
- `std/` — `math.ql`, `bits.ql`, `io.ql`, `input.ql`, `list.ql`, `vec.ql`, and `prelude.ql`
- `examples/` — small QL programs, all covered by golden tests
- `tests/` — the test suite

---

## Limitations and gotchas

- Array indexing is bounds-checked at compile time for literal indices and at run time for everything else, `array_push` / `array_pop` included.
- A `ptr` does not outlive the frame it points into.
- Collection is triggered only by allocation pressure or an explicit `gc()`. Every collection moves every surviving object that has somewhere lower to go.
- `float` is 32-bit single precision, so it carries about seven significant digits. There are no float arrays, no exponent notation in literals, and no `&` on a float.
- Comparing `str` values compares content, so ordering is lexicographic by byte. There is no case folding: `"Z" < "a"` is `true`.
- The process exit code carries only the low byte of `main`'s return value. Compile and runtime errors use 2 and 3, which a program may also return; stderr is the unambiguous signal.

- A variant must always be written `Enum::Variant`; there is no `use` to shorten it, and no inference of the enum from a match subject. Every use says which enum it belongs to.
- A match is a statement, not an expression. `let x = match (r) { ... }` is not a thing; an arm assigns or returns instead.
- `print` takes a variable name, not an expression. A `struct` already shows its fields, so `print p` covers most of what `print p.x` would.
- A shadowed name shows every declaration rather than the live one. The slot table carries no scope ranges, so which is in scope at a given pc is not knowable from it; showing all of them is honest where a guess would be confidently wrong.
- A breakpoint on a line with no code of its own moves forward to the next line that has some.
- A function value carries no captured environment, and a call names a variable or a function rather than an arbitrary expression, so `table[i](x)` and `f()(x)` go through a local first.

Future directions: scope ranges on the slot table, so a shadowed `print x` can name the live declaration; liveness analysis so a variable dead but still in scope stops rooting its object; and filling out `std/`.

The goal is to keep the compiler and VM small enough to read in one sitting and see exactly how each language feature works end to end.
