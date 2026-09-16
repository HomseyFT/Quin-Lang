// QuinLang Standard Library: a value or an explanation of its absence.
//
//     include "std/result.ql";
//
// Where Option says whether there is a value, Result says why there is not.
// The error type is the second parameter, so a function can fail with a string,
// a code, or a struct describing what went wrong.
//
// The usual way to consume one is to match it. The helpers here are for the
// cases where a match would be three lines saying one thing.

include "std/option.ql";

enum Result<T, E> { Ok(T), Err(E) }

fn result_is_ok<T, E>(r: Result<T, E>): bool {
    match (r) {
        Result::Ok(v) => { return true; }
        Result::Err(e) => { return false; }
    }
}

fn result_is_err<T, E>(r: Result<T, E>): bool {
    return !result_is_ok(r);
}

fn result_unwrap<T, E>(r: Result<T, E>): T {
    match (r) {
        Result::Ok(v) => { return v; }
        Result::Err(e) => { panic("result_unwrap called on Err"); }
    }
}

fn result_unwrap_or<T, E>(r: Result<T, E>, fallback: T): T {
    match (r) {
        Result::Ok(v) => { return v; }
        Result::Err(e) => { return fallback; }
    }
}

// Apply a function to the value, leaving an error alone. The error type is
// unchanged, which is what lets this chain.
fn result_map<T, E, U>(r: Result<T, E>, f: fn(T): U): Result<U, E> {
    match (r) {
        Result::Ok(v) => { return Result::Ok(f(v)); }
        Result::Err(e) => { return Result::Err(e); }
    }
}

// Forget why it failed. Useful where the caller has nothing to do with the
// error but still has to handle its absence.
fn result_ok<T, E>(r: Result<T, E>): Option<T> {
    match (r) {
        Result::Ok(v) => { return Option::Some(v); }
        Result::Err(e) => { return Option::None; }
    }
}

fn result_err<T, E>(r: Result<T, E>): Option<E> {
    match (r) {
        Result::Ok(v) => { return Option::None; }
        Result::Err(e) => { return Option::Some(e); }
    }
}

fn result_show<T, E>(r: Result<T, E>, show_ok: fn(T): str,
                     show_err: fn(E): str): str {
    match (r) {
        Result::Ok(v) => { return "Ok(" + show_ok(v) + ")"; }
        Result::Err(e) => { return "Err(" + show_err(e) + ")"; }
    }
}
