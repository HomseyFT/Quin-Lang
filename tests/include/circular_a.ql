// Circular include test A - includes B which includes A
// The resolver should handle this gracefully (only include each file once)
include "./circular_b.ql";

fn func_a(x: int): int {
    return x + 1;
}

fn main(): int {
    let a: int = func_a(5);
    let b: int = func_b(5);
    println(a);
    println(b);
    return 0;
}
