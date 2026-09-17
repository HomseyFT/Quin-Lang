// A tour of the standard library.
//
// The prelude brings in the modules that define only functions. The ones that
// declare a type are included by name, since a type name is global.

include "std/prelude.ql";
include "std/list.ql";
include "std/vec.ql";

fn square(n: int): int { return n * n; }
fn even(n: int): bool { return n % 2 == 0; }
fn add(a: int, b: int): int { return a + b; }
fn shout(s: str): str { return str_to_upper(s) + "!"; }

fn main(): int {
    println("-- math --");
    println(gcd(48, 18));            // 6
    println(lcm(4, 6));              // 12
    println(isqrt(50));              // 7  (7*7 = 49, 8*8 = 64)
    println(pow(2, 10));             // 1024
    println(pow(2, 16));             // 0 — wraps, like any 16-bit multiply
    println(clamp(99, 0, 10));       // 10
    println(sign(0 - 7));            // -1

    println("-- bits --");
    println(popcount(255));          // 8
    println(highest_bit(1000));      // 9
    println(trailing_zeros(8));      // 3
    print("0xBEEF = ");
    println_binary(48879);
    print("reversed  = ");
    println_hex(reverse_bits(48879));
    // >> is arithmetic, so shifting a negative number keeps its sign.
    // logical_shift_right is the version that does not.
    println(0 - 1 >> 8);             // -1
    println(logical_shift_right(0 - 1, 8));   // 255

    println("-- io --");
    print_line(12);
    print("|");
    print_padded(7, 5);
    print(" |");
    print_padded(1234, 5);
    println(" |");
    print_line(12);

    println("-- list --");
    // A list is persistent at the front: reversing builds a new one and
    // leaves the original intact.
    let l: List<int> = list_empty();
    for (let i = 5; i > 0; i = i - 1) {
        l = list_push(l, i);
    }
    println(list_show(l, int_to_str));              // [1, 2, 3, 4, 5]
    println(list_sum(l));                         // 15
    println(list_max(l));                         // 5
    println(list_show(list_reverse(l), int_to_str)); // [5, 4, 3, 2, 1]
    println(list_show(l, int_to_str));              // unchanged

    println("-- vec --");
    // A vector is a reference, so push is visible to whoever else holds it,
    // and the array it points at is traced and moved by the collector.
    let v: Vec<int> = vec_new(2);
    for (let i = 1; i < 8; i = i + 1) {
        vec_push(v, i * i);
    }
    println(vec_show(v, int_to_str));   // [1, 4, 9, 16, 25, 36, 49]
    println(vec_len(v));              // 7
    println(vec_capacity(v));         // 8 — grew from 2
    println(vec_sum(v));              // 140
    println(vec_pop(v));              // 49
    vec_reverse(v);
    println(vec_show(v, int_to_str));   // [36, 25, 16, 9, 4, 1]

    println("-- one container, any element --");
    // The same Vec at a reference element type. Nothing in std was written
    // twice to make this work; these are two instantiations of one module,
    // and the collector holds a different opinion about each.
    let words: Vec<str> = vec_new(2);
    vec_push(words, "generic");
    vec_push(words, "by");
    vec_push(words, "monomorphization");
    println(vec_show(words, show_str));
    println(vec_show(vec_map(words, shout), show_str));
    println(vec_len(vec_filter(words, is_long)));

    println("-- higher order --");
    println(vec_show(vec_map(v, square), int_to_str));
    println(vec_show(vec_filter(v, even), int_to_str));
    println(vec_fold(v, 0, add));
    println(option_show(vec_try_get(v, 99), int_to_str));  // None, not a panic

    gc();
    println(vec_show(v, int_to_str));      // survives being moved
    println(vec_show(words, show_str));  // and so do its strings
    println(list_show(l, int_to_str));

    return 0;
}

fn is_long(s: str): bool { return str_len(s) > 3; }
