// QuinLang Standard Library: a value that may be absent.
//
//     include "std/option.ql";
//
// The alternative is a sentinel -- 0 for "not found", null for "no value" --
// which works until the sentinel is also a legitimate value. An Option says
// which it is in the type, so the compiler makes you look.
//
// Option<T> costs one heap object when it is Some. None carries no payload, so
// the VM interns a single instance of it per instantiation and every None of
// that type is that same object.

enum Option<T> { Some(T), None }

fn option_is_some<T>(o: Option<T>): bool {
    match (o) {
        Option::Some(v) => { return true; }
        Option::None => { return false; }
    }
}

fn option_is_none<T>(o: Option<T>): bool {
    return !option_is_some(o);
}

// Panics on None. For the cases where absence really is a bug; use
// option_unwrap_or when it is not.
fn option_unwrap<T>(o: Option<T>): T {
    match (o) {
        Option::Some(v) => { return v; }
        Option::None => { panic("option_unwrap called on None"); }
    }
}

fn option_unwrap_or<T>(o: Option<T>, fallback: T): T {
    match (o) {
        Option::Some(v) => { return v; }
        Option::None => { return fallback; }
    }
}

// Apply a function to what is there, if anything. The element type may change:
// mapping int_to_str over an Option<int> gives an Option<str>.
fn option_map<T, U>(o: Option<T>, f: fn(T): U): Option<U> {
    match (o) {
        Option::Some(v) => { return Option::Some(f(v)); }
        Option::None => { return Option::None; }
    }
}

fn option_show<T>(o: Option<T>, show: fn(T): str): str {
    match (o) {
        Option::Some(v) => { return "Some(" + show(v) + ")"; }
        Option::None => { return "None"; }
    }
}
