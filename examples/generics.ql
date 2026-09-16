// Generics by monomorphization: a declaration with type parameters is a
// template, and each use with concrete arguments compiles a copy of it.
//
// Nothing generic survives compilation. `Vec<int>` and `Vec<str>` are two
// ordinary structs with two type ids, `push<int>` and `push<str>` two ordinary
// entries in the function table -- which is what lets the collector hold a
// different opinion about each one. A Vec<str> roots its elements; a Vec<int>
// has nothing to root, and neither of them pays for the other's answer.

struct Vec<T> {
    data: Array<T>,
    len: int,
}

enum Option<T> { Some(T), None }

fn vec_new<T>(capacity: int): Vec<T> {
    // A bare `Vec { ... }` takes its type arguments from the type this has to
    // return. Writing `Vec::<T> { ... }` would say the same thing out loud.
    return Vec { data: array_new(capacity), len: 0 };
}

fn push<T>(v: Vec<T>, value: T): void {
    if (v.len >= array_len(v.data)) {
        panic("vec is full");
    }
    v.data[v.len] = value;
    v.len = v.len + 1;
}

fn at<T>(v: Vec<T>, index: int): Option<T> {
    if (index < 0 || index >= v.len) {
        return Option::None;
    }
    return Option::Some(v.data[index]);
}

// The function that makes first-class functions pay: T and U are inferred from
// the vector and the function, so one definition maps int to str, str to int,
// or anything else.
fn map<T, U>(v: Vec<T>, f: fn(T): U): Vec<U> {
    let out: Vec<U> = vec_new(v.len);
    for (let i = 0; i < v.len; i = i + 1) {
        push(out, f(v.data[i]));
    }
    return out;
}

fn describe(n: int): str { return "#" + int_to_str(n); }
fn width(s: str): int { return str_len(s); }

fn main(): int {
    let nums: Vec<int> = vec_new(3);
    push(nums, 7);
    push(nums, 42);
    push(nums, 300);

    // Vec<int> to Vec<str>, and back again. Neither map is written twice.
    let names: Vec<str> = map(nums, describe);
    let widths: Vec<int> = map(names, width);

    // The strings exist only inside `names` by now, and the collector knows to
    // trace a Vec<str> because Vec<str> is its own layout.
    gc();

    for (let i = 0; i < names.len; i = i + 1) {
        match (at(names, i)) {
            Option::Some(s) => { print(s); print(" "); }
            Option::None => { print("?"); }
        }
    }
    println("");

    for (let i = 0; i < widths.len; i = i + 1) {
        print(widths.data[i]);
        print(" ");
    }
    println("");

    // Nothing says what this holds, so it is written out.
    let empty = vec_new::<str>(1);
    match (at(empty, 0)) {
        Option::Some(s) => { println(s); }
        Option::None => { println("empty"); }
    }

    return 0;
}
