// QuinLang Standard Library: a hash set.
//
//     include "std/set.ql";
//
// A Set<T> is a Map<T, bool> wearing the right name. That is deliberate: the
// probing, the tombstones and the growth are subtle enough that a second copy
// would be a second place for them to drift, and the only thing a set really
// wants that a map does not give is how it reads at the call site. The cost is
// one word per slot for a value array nobody looks at.
//
// Like the map, it carries its own hash, because a type parameter has no bounds
// to derive one from.

include "std/map.ql";

struct Set<T> {
    entries: Map<T, bool>,
}

fn set_new<T>(capacity: int, hash: fn(T): int): Set<T> {
    return Set { entries: map_new(capacity, hash) };
}

fn set_of<T>(item: T, hash: fn(T): int): Set<T> {
    let s: Set<T> = set_new(8, hash);
    set_add(s, item);
    return s;
}

// Returns whether the item was new, which is what makes a set useful for
// deduplicating in one pass rather than two.
fn set_add<T>(s: Set<T>, item: T): bool {
    if (map_has(s.entries, item)) {
        return false;
    }
    map_set(s.entries, item, true);
    return true;
}

fn set_has<T>(s: Set<T>, item: T): bool {
    return map_has(s.entries, item);
}

fn set_remove<T>(s: Set<T>, item: T): bool {
    return map_remove(s.entries, item);
}

fn set_len<T>(s: Set<T>): int {
    return map_len(s.entries);
}

fn set_is_empty<T>(s: Set<T>): bool {
    return map_is_empty(s.entries);
}

fn set_clear<T>(s: Set<T>): void {
    map_clear(s.entries);
}

// In slot order, which is not insertion order. Nothing about a hash set
// promises one.
fn set_items<T>(s: Set<T>): Array<T> {
    return map_keys(s.entries);
}

fn set_foreach<T>(s: Set<T>, f: fn(T): void): void {
    let items: Array<T> = set_items(s);
    for (let i = 0; i < array_len(items); i = i + 1) {
        f(items[i]);
    }
}

// -- combining --------------------------------------------------------------
//
// The reason a set is worth its own name. Each builds a new set and leaves both
// arguments alone, and each takes its hash from the left one.

fn set_union<T>(a: Set<T>, b: Set<T>): Set<T> {
    let out: Set<T> = set_new(set_len(a) + set_len(b) + 1, a.entries.hash);
    let left: Array<T> = set_items(a);
    for (let i = 0; i < array_len(left); i = i + 1) {
        set_add(out, left[i]);
    }
    let right: Array<T> = set_items(b);
    for (let i = 0; i < array_len(right); i = i + 1) {
        set_add(out, right[i]);
    }
    return out;
}

fn set_intersection<T>(a: Set<T>, b: Set<T>): Set<T> {
    let out: Set<T> = set_new(set_len(a) + 1, a.entries.hash);
    let left: Array<T> = set_items(a);
    for (let i = 0; i < array_len(left); i = i + 1) {
        if (set_has(b, left[i])) {
            set_add(out, left[i]);
        }
    }
    return out;
}

// Everything in `a` that is not in `b`.
fn set_difference<T>(a: Set<T>, b: Set<T>): Set<T> {
    let out: Set<T> = set_new(set_len(a) + 1, a.entries.hash);
    let left: Array<T> = set_items(a);
    for (let i = 0; i < array_len(left); i = i + 1) {
        if (!set_has(b, left[i])) {
            set_add(out, left[i]);
        }
    }
    return out;
}

fn set_is_subset<T>(a: Set<T>, b: Set<T>): bool {
    let left: Array<T> = set_items(a);
    for (let i = 0; i < array_len(left); i = i + 1) {
        if (!set_has(b, left[i])) {
            return false;
        }
    }
    return true;
}
