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

The driver lexes, resolves `include`s, type-checks, compiles to bytecode, and runs it in-process. Compile errors are reported as `Import error:`, `Semantic error:`, or `Codegen error:` with a `[line:col]` prefix; runtime faults come out as `Runtime error:`.

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

712 tests covering the lexer, parser, resolver, type checker, code generator, and VM. They run in about three seconds, so there's no reason not to run them on every change. See [Tests](#tests) for the layout.

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
- `ptr` — an address in the current frame, produced by `&`.
- `heapptr` — an address in the heap, produced by `alloc`.
- `void` — no value; only valid as a return type.
- `int[N]` — a fixed-size array of `N` ints in the current frame, for a literal `N > 0`.
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
Runtime error: Array index out of bounds at pc=12: index=5, length=3
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
println(n.value);      // Runtime error: Null pointer dereference reading a field
```

Rules worth knowing: a literal must give every field exactly once, in any order; fields are read and written but a struct has no value form for `print`; relational operators (`<`, `>`, …) do not apply to references; and a struct cannot have array-typed or `void` fields.

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
Runtime error: Float division by zero
Runtime error: Float overflow: 9.000000360735796e+40 does not fit in a 32-bit float
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
| `tests/test_driver.py` | The CLI as a real process: exit codes, warnings, error reporting |
| `tests/test_examples.py` | Every `examples/*.ql` against its golden output |
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
- `runtime/vm.py` — the QuinVM interpreter
- `std/` — `math.ql`, `bits.ql`, `io.ql`, `list.ql`, `vec.ql`, and `prelude.ql`
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

Future directions: a debugger (the source mapping it needs is still the cheap thing to front-load), liveness analysis so a variable dead but still in scope stops rooting its object, and filling out `std/`.

The goal is to keep the compiler and VM small enough to read in one sitting and see exactly how each language feature works end to end.
