// Test: Nested includes (A includes B, B includes C)
include "./nested_a.ql";

fn main(): int {
    // func_a is from nested_a.ql
    // func_b is from nested_b.ql (included by nested_a.ql)
    let x: int = func_a(5);  // 5 + 10 = 15
    let y: int = func_b(5);  // 5 * 2 = 10
    
    println(x);
    println(y);
    
    return 0;
}
