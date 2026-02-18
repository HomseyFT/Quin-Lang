// Circular include test B - includes A (creates cycle)
include "./circular_a.ql";

fn func_b(x: int): int {
    return x + 2;
}
