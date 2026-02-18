// Test: Diamond includes (main includes left+right, both include base)
// This tests that base.ql is only included once
include "./diamond_left.ql";
include "./diamond_right.ql";

fn main(): int {
    // base_func from diamond_base.ql (should only be included once)
    // left_func from diamond_left.ql
    // right_func from diamond_right.ql
    
    let a: int = base_func(5);   // 5 + 100 = 105
    let b: int = left_func(5);   // 5 + 1 = 6
    let c: int = right_func(5);  // 5 + 2 = 7
    
    println(a);
    println(b);
    println(c);
    
    return 0;
}
