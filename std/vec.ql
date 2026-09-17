// QuinLang Standard Library: a growable array of any element type.
//
//     include "std/vec.ql";
//
// The elements live in an Array<T>, so the collector decides what to trace from
// the array's own header: a Vec<str> has every element traced and rewritten when
// its strings move, and a Vec<int> is never traced at all. Neither pays for the
// other's answer, because Vec<int> and Vec<str> are two instantiations with two
// layouts, not one container holding a tagged element.
//
// The Vec itself is a struct, so it is a reference: push and set modify the
// caller's vector rather than a copy, and a reallocation is invisible to them.

include "std/option.ql";

struct Vec<T> {
    data: Array<T>,
    len: int,
    cap: int,
}

fn vec_new<T>(capacity: int): Vec<T> {
    if (capacity <= 0) {
        panic("vec_new needs a capacity of at least 1");
    }
    // A Vec { ... } here takes its element type from what this returns.
    return Vec { data: array_new(capacity), len: 0, cap: capacity };
}

// A one-element vector, for the same reason list_of exists: it starts a chain
// without anything else having to say what the elements are.
fn vec_of<T>(value: T): Vec<T> {
    let v: Vec<T> = vec_new(1);
    vec_push(v, value);
    return v;
}

fn vec_len<T>(v: Vec<T>): int {
    return v.len;
}

fn vec_capacity<T>(v: Vec<T>): int {
    return v.cap;
}

fn vec_is_empty<T>(v: Vec<T>): bool {
    return v.len == 0;
}

fn vec_get<T>(v: Vec<T>, index: int): T {
    if (index < 0 || index >= v.len) {
        panic("vec_get index out of range");
    }
    return v.data[index];
}

// The same read for callers that would rather branch than be stopped.
fn vec_try_get<T>(v: Vec<T>, index: int): Option<T> {
    if (index < 0 || index >= v.len) {
        return Option::None;
    }
    return Option::Some(v.data[index]);
}

fn vec_set<T>(v: Vec<T>, index: int, value: T): void {
    if (index < 0 || index >= v.len) {
        panic("vec_set index out of range");
    }
    v.data[index] = value;
}

// Double the capacity, copying the elements across. Reading v.data inside the
// loop matters: array_new above may have triggered a collection, which would
// have moved the old block and updated this field.
fn vec_grow<T>(v: Vec<T>): void {
    let new_cap: int = v.cap * 2;
    if (new_cap <= v.cap) {
        panic("vec capacity overflow");
    }
    let fresh: Array<T> = array_new(new_cap);
    for (let i = 0; i < v.len; i = i + 1) {
        fresh[i] = v.data[i];
    }
    v.data = fresh;
    v.cap = new_cap;
}

fn vec_push<T>(v: Vec<T>, value: T): void {
    if (v.len == v.cap) {
        vec_grow(v);
    }
    v.data[v.len] = value;
    v.len = v.len + 1;
}

fn vec_pop<T>(v: Vec<T>): T {
    if (v.len == 0) {
        panic("vec_pop called on an empty vector");
    }
    v.len = v.len - 1;
    return v.data[v.len];
}

fn vec_last<T>(v: Vec<T>): T {
    if (v.len == 0) {
        panic("vec_last called on an empty vector");
    }
    return v.data[v.len - 1];
}

// Forget the contents without releasing the block, so the capacity is reused.
// The elements above len stay in the array and stay reachable, which is worth
// knowing when they are references: they are not collected until overwritten.
fn vec_clear<T>(v: Vec<T>): void {
    v.len = 0;
}

// Equality is whatever '==' means for T: content for str, identity for a
// struct reference.
fn vec_contains<T>(v: Vec<T>, value: T): bool {
    for (let i = 0; i < v.len; i = i + 1) {
        if (v.data[i] == value) {
            return true;
        }
    }
    return false;
}

fn vec_index_of<T>(v: Vec<T>, value: T): int {
    for (let i = 0; i < v.len; i = i + 1) {
        if (v.data[i] == value) {
            return i;
        }
    }
    return 0 - 1;
}

fn vec_reverse<T>(v: Vec<T>): void {
    let i: int = 0;
    let j: int = v.len - 1;
    while (i < j) {
        let a: T = v.data[i];
        v.data[i] = v.data[j];
        v.data[j] = a;
        i = i + 1;
        j = j - 1;
    }
}

// -- higher order -----------------------------------------------------------

// The element type may change: mapping int_to_str over a Vec<int> gives a
// Vec<str>. Writing that down is what generics and function values are for.
fn vec_map<T, U>(v: Vec<T>, f: fn(T): U): Vec<U> {
    let out: Vec<U> = vec_new(v.len + 1);
    for (let i = 0; i < v.len; i = i + 1) {
        vec_push(out, f(v.data[i]));
    }
    return out;
}

fn vec_filter<T>(v: Vec<T>, keep: fn(T): bool): Vec<T> {
    let out: Vec<T> = vec_new(v.len + 1);
    for (let i = 0; i < v.len; i = i + 1) {
        if (keep(v.data[i])) {
            vec_push(out, v.data[i]);
        }
    }
    return out;
}

fn vec_fold<T, A>(v: Vec<T>, seed: A, op: fn(A, T): A): A {
    let total: A = seed;
    for (let i = 0; i < v.len; i = i + 1) {
        total = op(total, v.data[i]);
    }
    return total;
}

fn vec_foreach<T>(v: Vec<T>, f: fn(T): void): void {
    for (let i = 0; i < v.len; i = i + 1) {
        f(v.data[i]);
    }
}

fn vec_any<T>(v: Vec<T>, pred: fn(T): bool): bool {
    for (let i = 0; i < v.len; i = i + 1) {
        if (pred(v.data[i])) {
            return true;
        }
    }
    return false;
}

fn vec_all<T>(v: Vec<T>, pred: fn(T): bool): bool {
    for (let i = 0; i < v.len; i = i + 1) {
        if (!pred(v.data[i])) {
            return false;
        }
    }
    return true;
}

// Rendering needs a T -> str, which only the caller has. std/string.ql ships
// int_to_str and friends for the builtin types, since a builtin cannot be passed
// as a function value.
fn vec_show<T>(v: Vec<T>, show: fn(T): str): str {
    let out: str = "[";
    for (let i = 0; i < v.len; i = i + 1) {
        out = out + show(v.data[i]);
        if (i + 1 < v.len) {
            out = out + ", ";
        }
    }
    return out + "]";
}

// -- concrete where the element type is not free ----------------------------

fn vec_sum(v: Vec<int>): int {
    let total: int = 0;
    for (let i = 0; i < v.len; i = i + 1) {
        total = total + v.data[i];
    }
    return total;
}

fn vec_max(v: Vec<int>): int {
    if (v.len == 0) {
        panic("vec_max called on an empty vector");
    }
    let best: int = v.data[0];
    for (let i = 1; i < v.len; i = i + 1) {
        if (v.data[i] > best) {
            best = v.data[i];
        }
    }
    return best;
}

fn vec_min(v: Vec<int>): int {
    if (v.len == 0) {
        panic("vec_min called on an empty vector");
    }
    let best: int = v.data[0];
    for (let i = 1; i < v.len; i = i + 1) {
        if (v.data[i] < best) {
            best = v.data[i];
        }
    }
    return best;
}
