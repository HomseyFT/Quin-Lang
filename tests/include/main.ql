// Test: Basic include functionality
include "std/math.ql";
include "./helper.ql";

fn main(): int {
    let x: int = abs(0 - 42);  // Should be 42
    let y: int = double(21);   // Should be 42 (from helper.ql)
    
    println(x);
    println(y);
    
    // Test min/max
    let a: int = min(10, 20);
    let b: int = max(10, 20);
    println(a);  // 10
    println(b);  // 20
    
    // Test clamp
    let c: int = clamp(5, 0, 10);   // 5
    let d: int = clamp(15, 0, 10);  // 10
    let e: int = clamp(0 - 5, 0, 10);  // 0
    println(c);
    println(d);
    println(e);
    
    return 0;
}
