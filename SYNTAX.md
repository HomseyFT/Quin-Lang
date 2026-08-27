# QuinLang Syntax and Built-in Functions

The reference for QuinLang's surface syntax and built-ins. Programs are compiled to QuinVM bytecode and run with `python3 -m compiler.driver_vm`. See [README.md](README.md) for an overview of the pipeline.

## Lexical structure

- **Comments**: `// to end of line`. There are no block comments.
- **Identifiers**: start with a letter or `_`, then letters, digits, or `_`.
- **Keywords**: `fn let return if else while for break continue true false null int str void ptr heapptr print println vm_asm include struct`. These cannot be used as identifiers.
- **Integer literals**: decimal (`123`) or hexadecimal (`0xFF`, `0XFF`). A literal must fit in 16 bits (`0..65535`); larger values are a lex error. There are no negative literals — `-1` is the unary `-` operator applied to `1`.
- **Float literals**: digits, a `.`, then digits — `1.5`, `3.0`. Both sides are required: `1.` is a lex error, and `.5` does not parse as an expression at all. There is no exponent notation; `1e5` is a lex error rather than lexing as `1` followed by `e5`. A literal too large for a 32-bit float is rejected.
- **String literals**: `"..."`, delimited by double quotes, may span lines. The escapes `\n`, `\t`, `\r`, `\0`, `\\` and `\"` are recognised; any other character after a backslash is a lex error, so a typo is reported rather than silently kept as two characters. A `str` stores one byte per character, so a literal may only contain `U+0000` through `U+00FF`; a character above that is a lex error naming its codepoint. Source files are otherwise UTF-8 — the limit applies inside quotes, not to comments or the file at large.
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

`std/` provides `math.ql` (integer math), `bits.ql` (bit manipulation), `io.ql` (output helpers), `list.ql` (a linked list of ints), `vec.ql` (a growable int array), and `prelude.ql`, which includes the first three:

```quin
include "std/prelude.ql";     // math, bits, io
include "std/list.ql";        // IntList — opt in, it declares a struct
include "std/vec.ql";         // IntVec  — likewise
```

The collection modules stay out of the prelude because a struct name is global once included. See [README.md](README.md#multi-file-programs) for what each module contains.

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
- A non-void function must return on every path. The check is conservative: an `if` counts only when both branches return, and a `while` or `for` never counts because the body may not run.
- Redefining a function name is an error.

The entry point must be named `main`, take no parameters, and return `int` or `void`:

```quin
fn main(): int { return 0; }
fn main(): void { }
```

`main`'s return value becomes the process exit code. Only its low byte survives, as in C: `return 256` exits 0 and `return -1` exits 255.

The compiler warns when `main` returns a constant outside `0..255`, naming the exit code it will really produce, so that `return 256` is not mistaken for success. Constant arithmetic is folded, so `return 0 - 1` is caught too; a value the compiler cannot evaluate passes without comment.

A compile error exits `2` and a runtime error exits `3`, so the tool's own failures are distinct from a program returning `1`. Nothing reserves those values from a program, though — stderr is the only certain signal, and a clean run leaves it empty.

## Types

| Type | Meaning |
| --- | --- |
| `int` | 16-bit **signed** integer. Wraps on overflow; `/` truncates toward zero. |
| `float` | 32-bit IEEE 754 single precision, about seven significant digits. Two slots wide. Never mixes with `int` implicitly. See [Floats](#floats). |
| `bool` | `true` / `false`. Not implicitly convertible to or from `int`. |
| `str` | A string: a heap object holding its length and characters. Built with literals, `+`, slicing and conversion, and collected like any other object. There is no null string. |
| `ptr` | An address in the current frame, produced by `&`. See [Pointers](#pointers-and-address-of). |
| `heapptr` | An address in the heap, produced by `alloc`. See [Heap](#heap-alloc--heap_load--heap_store). |
| `void` | No value. Only valid as a return type. |
| `int[N]` | Fixed-size array of `N` ints in the current frame. `N` must be a positive integer literal. |
| a struct name | A reference to a heap object of that struct type. See [Structs](#structs). |

`bool` is a distinct type, not an alias for `0`/`1`: conditions must be `bool`, `true + 1` is a type error, and `if (1)` is rejected with `If condition must be bool`.

`ptr` and `heapptr` are both 16-bit addresses, but they index different memory and are **not** interchangeable. Assigning one to the other, comparing them, or passing one to an intrinsic expecting the other is a type error.

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
- The argument must be `int`, `str`, or `bool`. `ptr`, `heapptr`, `void`, and `int[N]` are rejected.
- `bool` prints as `true` / `false`; `println` adds a newline.
- Strings print verbatim. A `$` in a string is an ordinary character; it used to terminate DOS strings back when QuinLang targeted 8086, and carries no meaning now.

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

`condition` must have type `bool`. Each body is its own scope.

### For

```quin
for (let i: int = 0; i < 3; i = i + 1) {
    println(i);
}
```

The three clauses are init, condition, and step, separated by `;`. All are optional:

```quin
for (; i < 3; i = i + 1) { }   // no init
for (let i = 0;; i = i + 1) { }   // no condition: loops until a break
for (let i = 0; i < 3;) { }    // no step
for (;;) { }                   // no clauses at all
```

- The init clause is a `let` declaration, an assignment, or an expression. A `let` here declares the loop variable in a scope that wraps the loop, so it is visible to the condition, step, and body, but not after the loop — two consecutive loops may each declare `i`.
- The condition must have type `bool`, and an omitted condition means "always true".
- The step clause is an assignment or an expression, with no trailing `;`.
- The body is its own scope, nested inside the init's, so it may shadow the loop variable.
- Braces are required, as with `if` and `while`.

### Break and continue

```quin
break;
continue;
```

`break` exits the innermost enclosing loop. `continue` skips the rest of the current iteration. Both work in `while` and `for`, and both bind to the innermost loop when loops are nested.

In a `for` loop, `continue` jumps to the **step** clause, not to the condition, so the loop still advances:

```quin
for (let i = 0; i < 4; i = i + 1) {
    if (i == 1) { continue; }
    println(i);              // 0 2 3
}
```

Using either outside a loop is a semantic error (`'break' outside of a loop`). A loop in another function does not count — the check is per function.

### Block

```quin
{
    let x: int = 2;
    println(x);
}
```

A bare `{ ... }` is a statement that introduces a scope and nothing else. Declarations inside it are not visible after it, and may shadow outer names. Blocks may nest.

### `vm_asm`

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

`vm_asm { ... }` lowers directly to VM bytecode. Each instruction is a line ending in `;`.

The block must leave the operand stack at the depth it started, and may never pop below it. There are no jumps in the instruction set, so the effect is the sum of the instructions and both conditions are checked at compile time:

```
Codegen error: [2:5] vm_asm block leaves 1 value(s) on the operand stack; it must end balanced
Codegen error: [1:30] vm_asm 'add' needs 2 value(s) on the operand stack but the block has 1
```

Depth may rise and fall freely in between; only the ends and the floor are constrained.

#### `vm_asm` instruction set

| Instruction | Effect |
| --- | --- |
| `push_int N;` | Push the literal `N` (decimal, or `0x`-prefixed). |
| `load_local NAME;` | Push the value of local `NAME`. |
| `store_local NAME;` | Pop and store into local `NAME`. |
| `add; sub; mul; div; neg; not;` | Arithmetic and logical negation. |
| `cmp_eq; cmp_ne; cmp_lt; cmp_le; cmp_gt; cmp_ge;` | Pop two, push `0` or `1`. |

`NAME` must be a scalar local or parameter in scope; arrays are rejected — index them explicitly. Anything outside this table, including `mod`, is a codegen error. Note that this is a subset of the VM's opcodes; see [README.md](README.md#quinvm-bytecode) for the full set.

## Floats

```quin
let x: float = 1.5;
let y: float = 0.25;

println(x + y);        // 1.75
println(x * y);        // 0.375
println(x >= y);       // true
```

`+ - * /` and all six comparisons work on two floats. `%` and the bitwise and shift operators do not — they are integer operations, and applying one to a float is a semantic error naming `float_to_int`.

`float` never mixes with `int`. `x + 1` where `x` is a float is an error, not an implicit widening:

```
Semantic error: Cannot mix int and float; convert explicitly with int_to_float or float_to_int
```

`int_to_float` and `float_to_int` are the whole bridge between them; `float_to_int` truncates toward zero, matching integer `/`, and faults if the result leaves the 16-bit int range.

Two operations fault rather than yielding a value:

- **Division by zero** — as integer `/` already does.
- **Overflow past the 32-bit range** — because an infinity would make every later comparison quietly wrong, and there is no way to say so in a result.

### Float restrictions

A float is two slots wide, and each of the following addresses exactly one slot, so each is rejected rather than silently working on half a value:

| Written | Result |
| --- | --- |
| `let a: float[3];` | `Only int arrays exist; 'float[N]' is not a type` |
| `@x` where `x` is a float | `a float is two slots wide and a ptr addresses one` |
| `vm_asm { load_local x; }` | `'x' is a float, which is two slots wide; vm_asm only moves one` |

A float **may** be a struct field, a parameter, a return type, and a local. `main` may not return one — an exit code is an int.

Printing gives the shortest decimal that reads back as the same 32-bit value, always with a decimal point, so `3.0` never looks like an int. `float_to_str` produces that same text.

## Structs

```quin
struct Point {
    x: int,
    y: int,
}
```

A struct declaration is a top-level item, like a function. It may appear before or after the code that uses it, and it may come from an included file. A trailing comma after the last field is allowed.

A struct value is a **reference to a heap object**, not the object itself. One word wide, like every other reference.

- Fields are `name: Type` pairs. A field may be `int`, `bool`, `str`, `ptr`, `heapptr`, or another struct — including the struct being declared.
- Field types resolve in a second pass, so self-reference and forward reference both work.
- A field may not be an array (`int[N]`) or `void`.
- A struct must declare at least one field.
- Field names must be unique within a struct, and a struct name may not be redefined or shadow a built-in type.

### Struct literals

```quin
let p: Point = Point { x: 3, y: 4 };
let q = Point { y: 4, x: 3 };        // order is free; type is inferred
```

A literal allocates a new object. It must name **every** field exactly once; a missing, repeated, or unknown field is an error. Field values are evaluated in the order written.

### Field access

```quin
println(p.x);
p.y = 10;
l.a.x = 9;          // chains
```

The object must be a struct, and the field must exist. Assigning to a field requires a matching type. Reading or writing a field through `null` is a runtime error (`Null pointer dereference`).

### Reference semantics

```quin
let q: Point = p;   // q and p name the same object
q.x = 99;
println(p.x);       // 99
```

Consequences:

- Passing a struct to a function passes the reference, so the callee can modify the caller's object.
- `==` and `!=` compare **identity**, not field values: two literals with equal fields are not equal.
- `<`, `<=`, `>`, `>=` do not apply to struct references or to `null`.
- A struct has no printable form; `println(p)` is an error.
- Structs may be parameters and return types, unlike arrays.

### null

`null` is a reference literal at heap address 0. It initializes any reference type — any struct, or `heapptr` — and an uninitialized struct variable is already `null`:

```quin
let n: Node;
println(n == null);          // true
let m: Node = null;          // explicit
```

`null` has no type of its own, so it cannot be inferred: `let x = null;` is an error. It is not assignable to `int` or `ptr`, and a `Point` is never assignable to a `Node`.

## Sum types

### `enum`

```quin
enum Result {
    Ok(int),
    DivideByZero,
    NotADigit(int),
}
```

- Declared at the top level, like a struct, and visible across the whole merged program.
- A variant's payload is **positional**: types, not `name: type` pairs.
- A variant with no payload is written without parentheses. `A()` is a syntax error in a declaration and in a use — one value, one spelling.
- Every enum needs at least one variant, and no two variants of one enum may share a name.
- The **declaration** uses short names; `enum E { E::A }` is a syntax error. Every **use** is qualified, `E::A`.
- Two enums may declare the same short name, and a variant may share its short name with a struct, a function, or a variable — qualification keeps them distinct.
- A variant may carry its own enum, so `enum List { Nil, Cons(int, List) }` is legal; names are registered before payload types are resolved.
- A variant cannot carry an array or a `void`.

### Construction

```quin
let a: Result = Result::Ok(5);          // payload: a call
let b: Result = Result::DivideByZero;   // no payload: a bare name
let c: Result = null;                   // an enum reference is nullable
```

`Enum::Variant` is one name, not a path: `A::B::C` is a syntax error. An unqualified variant name is a compile error naming the spelling to use, and an unknown enum is reported as such.

A construction has the *enum's* type, not the variant's. There is no way to declare a variable of a variant type — `let x: Ok;` is not a thing.

### `match`

```quin
match (subject) {
    Result::Ok(value)    => { println(value); }
    Result::DivideByZero => { println("divided by zero"); }
    _                    => { println("something else"); }
}
```

- The subject is parenthesised, as in `if` and `while`. Required: `match r {` would parse as the struct literal `r { ... }`.
- Arms are not comma-separated; each ends in a block.
- The pattern is a qualified variant name, optionally binding its payload positionally, or `_` for the rest. Patterns are qualified like every other use: the subject's enum is known, but a name that means one thing in an arm and another everywhere else is worse than the repetition.
- `_` may not bind, and no arm may follow it.
- A variant may appear at most once.
- The binding count must equal the payload count.
- Bindings are ordinary locals scoped to their arm, so two arms may bind the same name and a binding may shadow an outer one.
- A match is a **statement**, not an expression.
- It must cover every variant, or carry a `_`. A `_` with nothing left to cover is a warning, not an error.
- Matching a null subject is a runtime fault: `Null reference in match`.

## Expressions

### Literals

```quin
123
0xFF        // hexadecimal
"Hello"     // string
true
false
null        // heapptr literal, equal to heap address 0
```

### Unary operators

```quin
-x      // arithmetic negation (int)
!flag   // logical not (bool)
~x      // bitwise not (int)
@x      // address-of (see below)
```

`-` and `~` require `int`, `!` requires `bool`, and `@` produces a `ptr`; anything else is a type error.

### Binary operators

```quin
// Arithmetic (int operands, int result)
a + b    a - b    a * b    a / b    a % b

// Bitwise (int operands, int result)
a ^ b    a | b    a & b    a << b   a >> b

// Comparisons (operands of the same type, bool result)
a == b   a != b   a < b    a <= b   a > b    a >= b

// Logical (bool operands, bool result, short-circuit)
a && b   a || b
```

- `/` truncates toward zero (`-7 / 2` is `-3`), and `%` takes the sign of the left operand (`-7 % 2` is `-1`). Division or modulo by zero is a runtime error.
- `int` arithmetic wraps at 16 bits.
- `^`, `|`, `&`, `<<`, and `>>` are bitwise operators; they require `int` operands and produce an `int`. `&` is binary bitwise AND, not address-of.
- Comparisons require both operands to have the *same* type; `1 == true` is an error.
- `&&` and `||` short-circuit — the right operand is not evaluated when the left decides the result.
- `+` on two `str` operands concatenates them, producing a new string.
- Comparing two `str` values compares their **content**, so `"apple" < "banana"` is `true`. Ordering is lexicographic by byte and does no case folding, which puts every uppercase letter before every lowercase one: `"Z" < "a"` is `true`.
- Relational operators do not apply to struct references or `null`; `==` and `!=` do, and compare identity.

Precedence, tightest first:

1. Postfix `()` (call), `[]` (index)
2. Unary `!`, `-`, `~`, `@`
3. `*`, `/`, `%`
4. `+`, `-`
5. `<<`, `>>`
6. Relational `<`, `<=`, `>`, `>=`
7. Equality `==`, `!=`
8. `&`
9. `^`
10. `|`
11. `&&`
12. `||`

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
- A **literal** index outside the array is rejected at compile time by sema — the same check whether you read `a[7]`, assign `a[7] = x`, or take `@a[7]`.
- Any other index is checked at run time against the array's own length by the `BOUNDS_CHECK` opcode, raising `Array index out of bounds`. The compile-time check does not fold constants, so `a[0 - 1]` is a run-time fault rather than a compile error; there are no negative literals, so a negative index is always caught this way.

### Pointers and address-of

```quin
let x: int;
let a: int[3];
let p: ptr;

p = @x;        // address of a variable
p = @a[1];     // address of an array element
```

A `ptr` is an **index into the current frame's locals**, not a machine address. Consequences:

- Pointers are only meaningful inside the frame that created them. Returning `@x` and dereferencing it in the caller reads an unrelated slot, or faults if the caller's frame is smaller.
- `memcpy` / `memset` counts are in **slots (16-bit words)**, not bytes.
- Heap addresses are a *separate* address space with its own type, `heapptr`. Mixing the two is a compile error, not a silent misread: `load16(alloc(2))` and `heap_load(@x)` are both rejected.
- `@` does **not** apply to a variable holding a reference — a `heapptr` or a struct:

  ```quin
  let h: heapptr = alloc(4);
  let p: ptr = @h;      // error: cannot take the address of 'h'
  ```

  A frame pointer to a reference slot would let `load16` read the address out as an `int` and `store16` put one back, which is the last way to hide a reference from the garbage collector. Address-of on `int` and `bool` variables and on array elements is unaffected.

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
| `alloc(size: int): heapptr` | Bump-allocate `size` bytes on the heap. |
| `heap_load(p: heapptr): int` | Read the word at heap address `p`. |
| `heap_store(p: heapptr, value: int): void` | Write `value` at heap address `p`. |
| `str_len(s: str): int` | The number of characters in `s`. |
| `str_char_at(s: str, i: int): int` | The character code at `i`. Panics if out of range. |
| `str_slice(s: str, start: int, end: int): str` | A new string with the characters in `[start, end)`. |
| `int_to_str(x: int): str` | The decimal text of `x`. |
| `char_to_str(code: int): str` | A one-character string for a code in `0..255`. |
| `int_to_float(n: int): float` | Widen an int. The only implicit-free way into `float`. |
| `float_to_int(x: float): int` | Truncate toward zero. Faults if the result is outside `-32768..32767`. |
| `float_to_str(x: float): str` | The same text `println` would print. |
| `read_line(): str` | The next input line **with its terminator**, or `""` at end of input. |
| `argc(): int` | How many arguments the host supplied. May be zero. |
| `argv(i: int): str` | Argument `i`. Faults if `i` is outside `0..argc() - 1`. |
| `gc(): void` | Force a garbage collection. |
| `panic(msg: str): void` | Stop the program, reporting `msg`. |
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

Both require `xs` to be a named local array, and both are bounds-checked against the element they touch: `xs[len]` for a push, `xs[len - 1]` for a pop. A literal length is a compile error, a computed one faults at run time, and popping at length 0 is caught as index `-1`. You still maintain `len` yourself — the check only stops a mistake from reaching a neighboring local.

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

`count` is in slots (16-bit words), not bytes:

```quin
let src: int[3];
let dst: int[3];

src[0] = 7;
src[1] = 8;
src[2] = 9;

memcpy(@dst[0], @src[0], 3);   // 3 elements
println(dst[0]);               // 7

memset(@dst[0], 0, 3);
println(dst[0]);               // 0
```

Overlapping `memcpy` ranges are handled: the copy runs back to front when the destination is above the source. A negative `count` is a runtime error; an overlong one silently walks into neighboring locals until it leaves the frame.

### `gc`

```quin
gc();
```

Forces a garbage collection. Collection also happens on its own whenever an allocation cannot be satisfied, so a program never needs to call this; it exists to make collection happen at a known point, which is useful in tests and when demonstrating the collector.

The collector is precise, sliding, and mark-compact. It traces from every reference reachable in a frame or on the operand stack, so cycles are reclaimed. Survivors are then slid together and every reference rewritten to follow them, which means there is no fragmentation and allocation is always a bump. See [Garbage collection](README.md#garbage-collection) in the README for how roots are found and why moving is safe.

### Strings

```quin
let name: str = "Ada";
let greeting: str = "hello, " + name + "!";
println(str_len(greeting));            // 12
println(str_slice(greeting, 7, 10));   // Ada
println(str_char_at(name, 0));         // 65
println(int_to_str(42) + "!");         // 42!
```

A string is a heap object, so building one allocates and the collector reclaims it when nothing refers to it. Literals are materialised into the heap at start-up and live for the whole run.

- Characters are bytes. `str_char_at` gives a code in `0..255` and `char_to_str` turns one back; there is no `char` type.
- `str_slice` takes a half-open range, so `str_slice(s, 0, str_len(s))` is the whole string and `str_slice(s, i, i)` is empty. A range outside the string panics.
- An uninitialised `str` is the empty string. There is no null string, and `null` is not assignable to a `str`.
- A string may contain a nul: the length is stored in the object, so `\0` is an ordinary character rather than a terminator.
- `std/string.ql` builds searching, trimming, case conversion and parsing on top of these.

### Input: `read_line` / `argc` / `argv`

`read_line()` keeps the line's terminator. That is what makes end of input
unambiguous: a blank line is `"\n"`, and only end of input is `""`.

```quin
while (true) {
    let line: str = read_line();
    if (str_len(line) == 0) { break; }   // end of input, never a blank line
    print(line);
}
```

Stripping the terminator inside `read_line` would make the last line of a file
indistinguishable from the end of it. `std/input.ql` wraps the convention in an
enum for code that would rather match than compare lengths:

```quin
include "std/input.ql";

match (next_line()) {
    Input::Line(text) => { println(text); }   // terminator already stripped
    Input::End        => { }
}
```

Input is **bytes**. A `str` holds one byte per character, so a UTF-8 character
arrives as several, and a character too wide for a byte is a runtime fault
rather than a silent mangling.

`argc()` counts what the host supplied and may be zero, so a program indexes
from 0 rather than assuming `argv(0)` exists. Run through the driver, `argv(0)`
is the program path and anything after it follows, as in C:

```bash
python3 -m compiler.driver_vm prog.ql alpha beta
```

Everything after the source file belongs to the program, so it may take flags
of its own without the driver claiming them.

### `panic`

```quin
panic("index out of range");
```

Stops the program and reports the message as a runtime error, with the position it fired at and the calls that led there:

```quin
fn check(ok: bool): int {
    if (!ok) { panic("index out of range"); }
    return 1;
}
fn main(): int {
    println(check(false));
    return 0;
}
```

```
Runtime error: [2:21] in check: index out of range
  at check (line 2)
  at main  (line 6)
```

Nothing else in the language can report a problem, so this is how a function rejects an argument it cannot handle. The standard library uses it throughout rather than returning a plausible wrong answer.

`panic` never returns, and the return checker knows it: a non-void function may end with a `panic` instead of a `return`.

```quin
fn checked(x: int): int {
    if (x >= 0) { return x; }
    panic("checked needs a non-negative value");
}
```

### Heap: `alloc` / `heap_load` / `heap_store`

```quin
let p: heapptr;

p = alloc(8);            // 8 bytes; sizes are rounded up to a multiple of 2
heap_store(p, 1234);
println(heap_load(p));   // 1234
```

- The heap is 64 KiB and collected automatically. There is no `free`: drop the last reference to an object and the collector reclaims it. Exhausting the heap with live objects is still a runtime error (`Heap out of memory`).
- Addresses are byte offsets; a word occupies two of them, so consecutive words are at `p`, `p + 2`, `p + 4`, ...
- Word accesses are bounds-checked against the heap, but nothing checks that an address belongs to the allocation you think it does.
- A collection moves objects, so the numeric value of a `heapptr` can change between one statement and the next. The collector rewrites every reference it can reach, including one pointing into the middle of a block, so this is invisible to a program — there is no way to observe an address as an integer.
- A `heapptr` cannot be passed to `load16` / `store16` / `memcpy` / `memset`, and a `ptr` cannot be passed to `heap_load` / `heap_store`. The type checker rejects both.
- `null` is a `heapptr` literal equal to heap address 0. Address 0 is reserved, so no allocation returns it.
- `heap_load(null)` or `heap_store(null, ...)` raises `Null pointer dereference`.
- `heapptr + int` and `heapptr - int` give a `heapptr`. `heapptr - heapptr` is **not** allowed: it was the only expression that turned a reference into an `int`, and removing it is what lets a collector assume an untyped block holds no references.
- Every allocation carries a two-word header below the returned address: the object's kind and mark bit, then its struct type id or byte size. `alloc` therefore consumes four bytes more than requested, and the smallest block is four bytes of payload.

### `ct_eq` / `ct_select`

Constant-time-*style* helpers. They preserve the intended semantics, but the VM makes no timing guarantee — `ct_eq` lowers to an ordinary comparison. The names describe intent, inherited from the 8086 backend where they lowered to branchless sequences.

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

- Array indexing is bounds-checked: a literal index outside the array is a compile error, and a computed one faults at run time. `array_push` and `array_pop` are checked the same way, against the index they touch — `len` for a push, `len - 1` for a pop.
- Pointers are untyped within their address space: a `ptr` is just a slot index, and nothing checks what kind of data lives there.
- Pointers do not outlive the frame they point into.
- A runtime error names its `[line:col]`, its function, and a backtrace. When the frames span more than one file each line names its file, since a line number alone is ambiguous across includes.
- `int` wraps at 16 bits; `float` is 32-bit single precision, and its two failure cases (division by zero, overflow) fault instead of producing infinity.
- A `float` is two slots wide, so there are no `float[N]` arrays, `@` does not apply to one, and `vm_asm` cannot name one.
- Comparing `str` values compares content. Ordering is lexicographic by byte, with no case folding, so `"Z" < "a"` is `true`.
- No methods, no arrays of structs, and no array-typed struct fields.
- The collector compacts, so there is no fragmentation: every free byte is usable no matter how scattered the garbage was. Objects move, but a `heapptr` is rewritten to follow its object, so it stays valid.
- Leaving a scope releases the references it declared, so a loop body or block stops rooting its objects as soon as it ends. A variable in the function's own top-level scope is still rooted until the function returns, even after its last use.
