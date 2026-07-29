# QuinLang Syntax and Built-in Functions

The reference for QuinLang's surface syntax and built-ins. Behavior described here is the **QuinVM backend** (`python3 -m compiler.driver_vm`), which is the supported one; where the 8086 backend differs, it is called out. See [README.md](README.md) for an overview and the backend comparison table.

## Lexical structure

- **Comments**: `// to end of line`. There are no block comments.
- **Identifiers**: start with a letter or `_`, then letters, digits, or `_`.
- **Keywords**: `fn let return if else while true false int str void ptr print println asm vm_asm include`. These cannot be used as identifiers.
- **Integer literals**: decimal (`123`) or hexadecimal (`0xFF`, `0XFF`). A literal must fit in 16 bits (`0..65535`); larger values are a lex error. There are no negative literals — `-1` is the unary `-` operator applied to `1`.
- **String literals**: `"..."`, delimited by double quotes, may span lines. There are **no escape sequences**: `\n` inside a string literal is a backslash followed by `n`.
- **Whitespace** is insignificant.

## Program structure

A file is zero or more `include` statements followed by one or more function definitions:

```quin
include "std/math.ql";

fn main(): int {
    return 0;
}
```

`include` must come before every function definition; an `include` later in the file is a syntax error.

### `include`

```quin
include "std/math.ql";     // resolved against the project's std/ directory
include "./helpers.ql";    // resolved relative to the including file
include "../lib/util.ql";
```

The resolver parses included files recursively (depth-first) and merges their functions into a single program. A file included twice, directly or through a cycle, is only processed once. Two files defining the same function name is an error.

`std/` currently provides `math.ql`: `abs(x)`, `min(a, b)`, `max(a, b)`, `clamp(x, lo, hi)`. `std/io.ql` and `std/prelude.ql` exist but are empty.

### Functions

```quin
fn name(param1: Type1, param2: Type2): ReturnType {
    // statements
}
```

- Parameters are `name: Type` pairs separated by commas.
- `: ReturnType` may be omitted, which makes the function `void`.
- Parameters may not be array types (`int[N]`), and a function may not return an array type.
- Functions may be called before their definition, and may recurse.
- A non-void function must return on every path. The check is conservative: an `if` counts only when both branches return, and a `while` never counts because the body may not run.
- Redefining a function name is an error.

The entry point must be named `main`, take no parameters, and return `int` or `void`:

```quin
fn main(): int { return 0; }
fn main(): void { }
```

`main`'s return value is the VM's exit value, but the driver does not propagate it to the process exit code.

## Types

| Type | Meaning |
| --- | --- |
| `int` | 16-bit **signed** integer. Wraps on overflow; `/` truncates toward zero. |
| `bool` | `true` / `false`. Not implicitly convertible to or from `int`. |
| `str` | String literal; on the VM an interned id into a string table. |
| `ptr` | Untyped address. See [Pointers](#pointers-and-address-of). |
| `void` | No value. Only valid as a return type. |
| `int[N]` | Fixed-size array of `N` ints in the current frame. `N` must be a positive integer literal. |

`bool` is a distinct type, not an alias for `0`/`1`: conditions must be `bool`, `true + 1` is a type error, and `if (1)` is rejected with `If condition must be bool`.

### Array restrictions

`int[N]` is deliberately second-class. All of the following are semantic errors:

```quin
fn f(a: int[3]) { }          // arrays cannot be parameters
fn g(): int[3] { }           // arrays cannot be returned
let a: int[3] = something;   // arrays cannot have an initializer
a = b;                       // arrays cannot be assigned as a whole
println(a);                  // arrays have no value form
```

An array is zeroed at declaration and filled element by element. `array_push` / `array_pop`, indexing, and `&a[i]` all require the array to be a **named local**.

## Statements

### Variable declaration

```quin
let x: int;            // zero-initialized
let x: int = 42;       // declared and initialized
let y = 42;            // type inferred from the initializer
let s = "hi";
let a: int[3];         // all elements zero
```

- The type annotation may be omitted only when there is an initializer; `let x;` fails with `Cannot infer type for 'x' without initializer`.
- With both, the annotation and the initializer's type must match exactly — there are no implicit conversions.
- The initializer is evaluated before the name is bound, so `let x = x + 1;` reads an outer `x`.
- Redeclaring a name in the same scope is an error. Declaring it in an inner block shadows the outer one.

### Assignment

```quin
x = 5;
x = x + 1;
a[i] = x;
```

The left-hand side is a variable name or an array element. Assignment is a **statement**, not an expression, so `x = y = 0;` and `if (x = 1)` do not parse. The value's type must match the target's exactly.

### Expression statement

```quin
some_function();
array_push(a, len, 10);
```

Any expression followed by `;`. The value is discarded.

### Printing

```quin
print(x);
println(x);
print("Hello");
println(true);          // prints: true
```

- `print` and `println` are **statements with call-like syntax**, not functions: they are keywords, take exactly one argument, and cannot be used as values.
- The argument must be `int`, `str`, or `bool`. `ptr`, `void`, and `int[N]` are rejected.
- `bool` prints as `true` / `false`; `println` adds a newline.
- Strings print verbatim on the VM. The `$` terminator seen in older examples is an 8086/DOS convention and prints as a literal `$` under the VM.

### Return

```quin
return;
return 0;
return x + 1;
```

- A `void` function may only use `return;`; returning a value is an error.
- A non-void function must return a value whose type matches the declared return type.

### If / else

```quin
if (condition) {
    // then block
} else {
    // else block (optional)
}
```

`condition` must have type `bool`. Braces are required — there is no single-statement form. Each block is its own scope.

### While

```quin
while (condition) {
    // body
}
```

`condition` must have type `bool`. There is no `for`, `break`, or `continue`.

### Inline assembly (8086 backend only)

```quin
asm "mov ax, 1";

asm "mov ax, 1
add ax, 2";
```

- Splices the string into the generated `.asm` as raw lines.
- For more than one instruction, the string must contain **real newlines**, as above. Since string literals have no escape sequences, `asm "mov ax, 1\nadd ax, 2";` emits the single broken line `mov ax, 1\nadd ax, 2`.
- Only the 8086 backend (`compiler.driver`) emits it; the VM backend parses `asm` and ignores it.
- You are responsible for the calling convention, stack discipline, and callee-saved registers.

### `vm_asm` (VM backend only)

```quin
fn main(): int {
    let x: int = 5;
    vm_asm {
        load_local x;
        push_int 1;
        add;
        store_local x;
    }
    println(x);   // 6
    return 0;
}
```

`vm_asm { ... }` lowers directly to VM bytecode. Each instruction is a line ending in `;`. The 8086 backend rejects `vm_asm` blocks.

The block is emitted verbatim with no verification that it leaves the operand stack balanced. If it doesn't, the VM reports `Unbalanced operand stack at RET` when the enclosing function returns.

#### `vm_asm` instruction set

| Instruction | Effect |
| --- | --- |
| `push_int N;` | Push the literal `N` (decimal, or `0x`-prefixed). |
| `load_local NAME;` | Push the value of local `NAME`. |
| `store_local NAME;` | Pop and store into local `NAME`. |
| `add; sub; mul; div; neg; not;` | Arithmetic and logical negation. |
| `cmp_eq; cmp_ne; cmp_lt; cmp_le; cmp_gt; cmp_ge;` | Pop two, push `0` or `1`. |

`NAME` must be a scalar local or parameter in scope; arrays are rejected — index them explicitly. Anything outside this table, including `mod`, is a codegen error. Note that this is a subset of the VM's opcodes; see [README.md](README.md#quinvm-bytecode) for the full set.

## Expressions

### Literals

```quin
123
0xFF        // hexadecimal
"Hello"     // string
true
false
```

### Unary operators

```quin
-x      // arithmetic negation (int)
!flag   // logical not (bool)
&x      // address-of (see below)
```

`-` requires `int` and `!` requires `bool`; anything else is a type error.

### Binary operators

```quin
// Arithmetic (int operands, int result)
a + b    a - b    a * b    a / b    a % b

// Comparisons (operands of the same type, bool result)
a == b   a != b   a < b    a <= b   a > b    a >= b

// Logical (bool operands, bool result, short-circuit)
a && b   a || b
```

- `/` truncates toward zero (`-7 / 2` is `-3`), and `%` takes the sign of the left operand (`-7 % 2` is `-1`). Division or modulo by zero is a runtime error.
- `int` arithmetic wraps at 16 bits.
- Comparisons require both operands to have the *same* type; `1 == true` is an error.
- `&&` and `||` short-circuit — the right operand is not evaluated when the left decides the result.

Precedence, tightest first:

1. Postfix `()` (call), `[]` (index)
2. Unary `!`, `-`, `&`
3. `*`, `/`, `%`
4. `+`, `-`
5. Relational `<`, `<=`, `>`, `>=`
6. Equality `==`, `!=`
7. `&&`
8. `||`

All binary operators are left-associative. Parentheses group as usual.

### Arrays and indexing

```quin
let a: int[3];
a[0] = 10;
a[1] = 20;
println(a[2]);
```

- The index must be `int`; elements are always `int`.
- The base must be a named local array.
- **No bounds checking.** An out-of-range index reads or writes the neighboring local slot; the VM only faults (`Local index out of range`) when the index leaves the frame entirely.

### Pointers and address-of

```quin
let x: int;
let a: int[3];
let p: ptr;

p = &x;        // address of a variable
p = &a[1];     // address of an array element
```

On the VM a `ptr` is an **index into the current frame's locals**, not a machine address. Consequences:

- Pointers are only meaningful inside the frame that created them. Returning `&x` and dereferencing it in the caller reads an unrelated slot, or faults if the caller's frame is smaller.
- `memcpy` / `memset` counts are in **slots (16-bit words)**, not bytes. (The 8086 backend counts bytes.)
- Heap addresses from `alloc` are byte offsets into a *separate* address space, but carry the same `ptr` type. Mixing the two — `load16` on an `alloc`ed pointer, or `heap_load` on `&x` — compiles and silently reads the wrong memory.

### Function calls

```quin
foo();
bar(1, 2);
len = array_push(a, len, 10);
```

Argument count and types must match the signature exactly. Arguments are evaluated left to right. A `void` call may only be used as an expression statement.

## Built-in functions

Always available and lowered directly by the compiler; they cannot be shadowed by user functions.

| Signature | Summary |
| --- | --- |
| `array_push(xs: int[N], len: int, value: int): int` | Write `value` at `xs[len]`, return `len + 1`. |
| `array_pop(xs: int[N], len: int): int` | Return `xs[len - 1]`. Does not update `len`. |
| `load16(p: ptr): int` | Read the word at `p`. |
| `store16(p: ptr, value: int): void` | Write `value` at `p`. |
| `memcpy(dst: ptr, src: ptr, count: int): void` | Copy `count` slots. |
| `memset(dst: ptr, value: int, count: int): void` | Fill `count` slots with `value`. |
| `alloc(size: int): ptr` | Bump-allocate `size` bytes on the heap. |
| `heap_load(p: ptr): int` | Read the word at heap address `p`. |
| `heap_store(p: ptr, value: int): void` | Write `value` at heap address `p`. |
| `ct_eq(a: int, b: int): bool` | Equality, intended to be branchless. |
| `ct_select(mask: int, x: int, y: int): int` | `x` when `mask` is 1, else `y`. |

### `array_push` / `array_pop`

An `int[N]` has no length of its own, so you carry one:

```quin
let xs: int[3];
let len: int;
let v: int;

len = array_push(xs, len, 10);   // len = 1
len = array_push(xs, len, 20);   // len = 2

v = array_pop(xs, len);          // v = 20
len = len - 1;                   // you must decrement it yourself
```

Neither checks bounds, and both require `xs` to be a named local array. Pushing at `len >= N` writes past the array.

### `load16` / `store16`

```quin
let x: int;
let p: ptr;

p = &x;
store16(p, 4321);
println(x);            // 4321
println(load16(p));    // 4321
```

These operate on frame slots on the VM. Use `heap_load` / `heap_store` for heap addresses.

### `memcpy` / `memset`

`count` is in slots on the VM and in bytes on the 8086 backend:

```quin
let src: int[3];
let dst: int[3];

src[0] = 7;
src[1] = 8;
src[2] = 9;

memcpy(&dst[0], &src[0], 3);   // 3 elements
println(dst[0]);               // 7

memset(&dst[0], 0, 3);
println(dst[0]);               // 0
```

Overlapping `memcpy` ranges are handled: the copy runs back to front when the destination is above the source. A negative `count` is a runtime error; an overlong one silently walks into neighboring locals until it leaves the frame.

### Heap: `alloc` / `heap_load` / `heap_store`

```quin
let p: ptr;

p = alloc(8);            // 8 bytes; sizes are rounded up to a multiple of 2
heap_store(p, 1234);
println(heap_load(p));   // 1234
```

- The heap is 64 KiB and managed by a bump pointer. There is no `free` and no reuse; exhausting it is a runtime error (`Heap out of memory`).
- Addresses are byte offsets; a word occupies two of them, so consecutive words are at `p`, `p + 2`, `p + 4`, ...
- Word accesses are bounds-checked against the heap, but nothing checks that an address came from `alloc` or belongs to the allocation you think it does.
- The 8086 backend does not implement these — it emits a call to a symbol that does not exist.

### `ct_eq` / `ct_select`

Constant-time-*style* helpers. The 8086 backend lowers them to branchless sequences; the VM preserves the semantics but makes no timing guarantee.

```quin
let x: int = 1234;
let y: int = 1234;

if (ct_eq(x, y)) {
    println("equal");
}

let a: int = 10;
let b: int = 20;
println(ct_select(1, a, b));   // 10
println(ct_select(0, a, b));   // 20
```

`ct_select` is computed as `y + mask * (x - y)`, so `mask` must be `0` or `1` — any other value scales the difference instead of selecting. Note that `ct_select` evaluates `y` twice, so avoid passing an expression with side effects.

## Notes and limitations

- No bounds checking on array indexing or `array_push` / `array_pop`.
- `ptr` is untyped and overloaded: frame-slot pointers and heap addresses share a type but not an address space.
- Pointers do not outlive the frame they point into.
- `int` is the only numeric type: 16-bit, signed, wrapping.
- Comparing `str` values compares interned ids, so `==` and `!=` work as expected but `<` / `>` are meaningless (`"b" < "a"` is `true`).
- No `for`, `break`, `continue`, block statements, structs, or user-defined types.
- No escape sequences in string literals.
- The 8086 backend lags the language; see the table in [README.md](README.md#backend-status).
