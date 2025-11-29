# QuinLang Syntax and Built-in Functions

This document describes the current surface syntax of QuinLang and the built-in functions available to programs.

## Basic structure

### Functions

```quin
fn name(param1: Type1, param2: Type2, ...): ReturnType {
    // statements
}
```

- `name`: identifier for the function.
- Parameters: `name: Type` pairs separated by commas.
- `ReturnType` may be omitted for `void` functions.
- Entry point must be `fn main(): int { ... }`.

### Types

- `int` – 16-bit signed integer.
- `str` – pointer to a `$`-terminated DOS string.
- `bool` – boolean (`true` / `false`).
- `void` – no value.
- `ptr` – generic 16-bit pointer.
- `int[N]` – fixed-size array of `N` `int` elements stored on the stack (e.g. `int[3]`).

## Statements

### Variable declaration

```quin
let x: int;
let x: int = 42;
let s: str;
let p: ptr;
let a: int[3];
```

- `let name: Type;` declares an uninitialized variable.
- `let name: Type = expr;` declares and initializes a variable.

### Assignment

```quin
x = 5;
x = x + 1;
a[0] = 10;
a[i] = x;
```

- Left-hand side can be:
  - A variable name (`x`).
  - An array element (`a[i]`) for `int[N]` arrays.

### Expression statement

```quin
some_function();
array_push(a, len, 10);
```

Any expression followed by `;` that is not a declaration or control-flow statement.

### Printing

```quin
print(x);
print("Hello, world$");
println(x);
println("Done$");
```

- `print(expr);` – prints an `int` or `str` without a newline.
- `println(expr);` – prints an `int` or `str` followed by a newline (CRLF).

### Return

```quin
return;
return 0;
return x + 1;
```

- In `void` functions, `return;` ends the function.
- In non-void functions, `return expr;` returns a value.

### If / else

```quin
if (condition) {
    // then block
} else {
    // else block (optional)
}
```

- `condition` is any expression that evaluates to `bool` or `int` (nonzero treated as true at codegen level).

### While

```quin
while (condition) {
    // body
}
```

Loops while `condition` is true.

## Expressions

### Literals

```quin
123
0xFF      // hexadecimal int
"Hello$" // string (must be '$'-terminated for DOS printing)
true
false
```

### Variables and identifiers

```quin
x
my_var
```

### Unary operators

```quin
-x     // arithmetic negation
!flag  // logical not
```

### Binary operators

```quin
// Arithmetic
x + y
x - y
x * y
x / y

// Comparisons (return bool)
x == y
x != y
x < y
x <= y
x > y
x >= y

// Logical (short-circuit)
a && b
a || b
```

Operator precedence (highest to lowest):

- `!`
- `*`, `/`
- `+`, `-`
- comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`)
- `&&`
- `||`

### Arrays and indexing

```quin
let a: int[3];
a[0] = 10;
a[1] = 20;
print(a[2]);
```

- Arrays are fixed-size `int[N]` on the stack.
- Index expression: `array_expr[index_expr]`.
- Index must be an `int`.

### Pointers and address-of

```quin
let x: int;
let p: ptr;

p = &x;        // address of variable
p = &a[1];     // address of array element
```

- `&variable` – address of a local variable (type `ptr`).
- `&array[index]` – address of an array element (type `ptr`).

### Function calls

```quin
foo();
bar(1, 2);
print(x);
println("Hi$");
len = array_push(a, len, 10);
```

- `callee(arg1, arg2, ...)`.
- Arguments and return types must match the function signature.

## Built-in functions

These functions are always available; they are lowered directly by the compiler.

### `print`

```quin
print(value: int | str): void
```

Prints an integer or string without a newline.

### `println`

```quin
println(value: int | str): void
```

Prints an integer or string followed by a newline.

### `array_push`

```quin
array_push(xs: int[N], len: int, value: int): int
```

- Treats `xs` as an `int[N]` stack array and `len` as the current logical length.
- Writes `value` into `xs[len]` (no bounds checking yet).
- Returns `len + 1` as a new length.
- Typical usage:

```quin
len = 0;
len = array_push(xs, len, 10);
len = array_push(xs, len, 20);
```

### `array_pop`

```quin
array_pop(xs: int[N], len: int): int
```

- Returns the value at `xs[len - 1]`.
- Does **not** update `len`; the caller should decrement it:

```quin
v = array_pop(xs, len);
len = len - 1;
```

No bounds checking is performed yet.

### `load16`

```quin
load16(p: ptr): int
```

- Interprets `p` as a pointer to a 16-bit word.
- Returns the 16-bit value stored at that address.

Example:

```quin
let x: int;
let p: ptr;

x = 1234;
p = &x;
println(load16(p));  // prints 1234
```

### `store16`

```quin
store16(p: ptr, value: int): void
```

- Writes `value` to the 16-bit word pointed to by `p`.

Example:

```quin
let x: int;
let p: ptr;

p = &x;
store16(p, 4321);
println(x);   // prints 4321
```

### `memcpy`

```quin
memcpy(dst: ptr, src: ptr, count: int): void
```

- Copies `count` bytes from `src` to `dst`.
- Operates on raw bytes; caller is responsible for providing valid pointers and sizes.

Typical array use:

```quin
let buf1: int[3];
let buf2: int[3];

buf1[0] = 7;
buf1[1] = 8;
buf1[2] = 9;

memcpy(&buf2[0], &buf1[0], 6);  // 3 ints * 2 bytes
println(buf2[0]);  // 7
println(buf2[1]);  // 8
println(buf2[2]);  // 9
```

### `memset`

```quin
memset(dst: ptr, value: int, count: int): void
```

- Fills `count` bytes at `dst` with the low 8 bits of `value`.

Example:

```quin
let buf: int[3];

buf[0] = 7;
buf[1] = 8;
buf[2] = 9;

memset(&buf[0], 0, 6);  // zero 3 ints
println(buf[0]);  // 0
println(buf[1]);  // 0
println(buf[2]);  // 0
```

## Notes and limitations

- No dynamic allocation yet; all arrays are fixed-size `int[N]` on the stack.
- No bounds checking on array indexing or `array_push/array_pop`.
- `ptr` is untyped; it is up to you to ensure you point at the right kind of data.
- Strings printed with `print`/`println` must be `$`-terminated for DOS.
