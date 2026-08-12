// QuinLang Standard Library: output helpers.
//
// `print` and `println` are statements rather than functions, so they cannot be
// passed around or built on directly. These wrappers are how output becomes
// composable.

fn newline(): void {
    println("");
}

fn print_repeat(s: str, times: int): void {
    for (let i = 0; i < times; i = i + 1) {
        print(s);
    }
}

fn print_spaces(count: int): void {
    print_repeat(" ", count);
}

fn print_line(width: int): void {
    print_repeat("-", width);
    newline();
}

// One hexadecimal character for a value in 0..15. There is no way to build a
// string at run time, so every digit is a literal.
fn hex_digit(d: int): str {
    if (d == 0) { return "0"; }
    if (d == 1) { return "1"; }
    if (d == 2) { return "2"; }
    if (d == 3) { return "3"; }
    if (d == 4) { return "4"; }
    if (d == 5) { return "5"; }
    if (d == 6) { return "6"; }
    if (d == 7) { return "7"; }
    if (d == 8) { return "8"; }
    if (d == 9) { return "9"; }
    if (d == 10) { return "a"; }
    if (d == 11) { return "b"; }
    if (d == 12) { return "c"; }
    if (d == 13) { return "d"; }
    if (d == 14) { return "e"; }
    if (d == 15) { return "f"; }
    panic("hex_digit expects a value in 0..15");
}

// All four hex digits of x, most significant first. Masking matters: `>>` is
// an arithmetic shift, so a negative x would otherwise carry its sign down.
fn print_hex(x: int): void {
    for (let i = 3; i >= 0; i = i - 1) {
        print(hex_digit((x >> (i * 4)) & 15));
    }
}

fn println_hex(x: int): void {
    print_hex(x);
    newline();
}

// All sixteen bits of x, most significant first.
fn print_binary(x: int): void {
    for (let i = 15; i >= 0; i = i - 1) {
        print(hex_digit((x >> i) & 1));
    }
}

fn println_binary(x: int): void {
    print_binary(x);
    newline();
}

// The int printed right-aligned in a field of the given width. Useful for
// lining columns up, since there is no formatting syntax.
fn print_padded(value: int, width: int): void {
    let digits: int = 1;
    let rest: int = value / 10;
    while (rest != 0) {
        digits = digits + 1;
        rest = rest / 10;
    }
    if (value < 0) {
        digits = digits + 1;
    }
    print_spaces(width - digits);
    print(value);
}
