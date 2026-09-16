// Generics by monomorphization: a declaration with type parameters is a
// template, and each use with concrete arguments compiles a copy of it.
//
// Nothing generic survives compilation. `Vec<int>` and `Vec<str>` are two
// ordinary structs with two type ids, `vec_push<int>` and `vec_push<str>` two
// ordinary entries in the function table -- which is what lets the collector
// hold a different opinion about each one. A Vec<str> roots its elements; a
// Vec<int> has nothing to root, and neither pays for the other's answer.
//
// The container here is the library's. What this example writes is the generic
// *functions* over it, which is the half you write yourself.

include "std/vec.ql";
include "std/string.ql";

// T and U are inferred from the vector and the function, so one definition
// takes int to str, str to int, or anything else. This is std's vec_map,
// written out to show the shape.
fn mapped<T, U>(v: Vec<T>, f: fn(T): U): Vec<U> {
    let out: Vec<U> = vec_new(v.len + 1);
    for (let i = 0; i < v.len; i = i + 1) {
        vec_push(out, f(vec_get(v, i)));
    }
    return out;
}

// A generic function need not mention its parameter in every argument: A is
// fixed by the seed, T by the vector.
fn reduced<T, A>(v: Vec<T>, seed: A, op: fn(A, T): A): A {
    let total: A = seed;
    for (let i = 0; i < v.len; i = i + 1) {
        total = op(total, vec_get(v, i));
    }
    return total;
}

// One pair of values, at two independent types.
struct Pair<A, B> {
    first: A,
    second: B,
}

fn pair_of<A, B>(first: A, second: B): Pair<A, B> {
    return Pair { first: first, second: second };
}

fn describe(n: int): str { return "#" + show_int(n); }
fn width(s: str): int { return str_len(s); }
fn longer(best: int, s: str): int {
    if (str_len(s) > best) {
        return str_len(s);
    }
    return best;
}

fn main(): int {
    let nums: Vec<int> = vec_new(3);
    vec_push(nums, 7);
    vec_push(nums, 42);
    vec_push(nums, 300);

    // Vec<int> to Vec<str>, and back again. Neither map is written twice.
    let names: Vec<str> = mapped(nums, describe);
    let widths: Vec<int> = mapped(names, width);

    // The strings exist only inside `names` by now, and the collector traces a
    // Vec<str> because Vec<str> is its own layout.
    gc();

    println(vec_show(names, show_str));
    println(vec_show(widths, show_int));

    // The accumulator type is free of the element type: str elements, int total.
    println(reduced(names, 0, longer));

    // Two type parameters, bound independently at the call.
    let tagged: Pair<str, int> = pair_of("answer", 42);
    println(tagged.first);
    println(tagged.second);

    // Nothing says what this holds, so it is written out.
    let empty = vec_new::<str>(1);
    println(option_show(vec_try_get(empty, 0), show_str));

    return 0;
}
