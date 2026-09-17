// QuinLang Standard Library: text to values, reporting rather than stopping.
//
//     include "std/parse.ql";
//
// std/string.ql's str_parse_int panics on anything malformed, which is right
// for text you wrote yourself and useless for text that arrived from a file,
// an argument or a user. These return an Option instead, so a bad input is a
// value the caller has to account for rather than the end of the program.
//
// This is a module of its own because it includes std/option.ql, which declares
// a type -- and std/string.ql is in the prelude, where nothing may.

include "std/option.ql";
include "std/string.ql";

// The largest magnitude a 16-bit signed int holds on the positive side. The
// negative side reaches one further, which parse_int handles on its own.
fn parse_int_limit(): int {
    return 32767;
}

// A decimal int, with an optional leading '+' or '-'. None for an empty string,
// a sign with no digits, any character that is not a digit, or a value too
// large to hold -- which matters more here than in most languages, since that
// ceiling is 32767.
fn parse_int(s: str): Option<int> {
    let n: int = str_len(s);
    if (n == 0) {
        return Option::None;
    }
    // The one value whose magnitude does not fit on the positive side, so it
    // cannot be accumulated the way every other one is.
    if (s == "-32768") {
        return Option::Some(0 - parse_int_limit() - 1);
    }
    let i: int = 0;
    let negative: bool = false;
    let first: int = str_char_at(s, 0);
    if (first == 45) {          // '-'
        negative = true;
        i = 1;
    }
    if (first == 43) {          // '+'
        i = 1;
    }
    if (i == n) {
        return Option::None;
    }
    let value: int = 0;
    while (i < n) {
        let code: int = str_char_at(s, i);
        if (!is_digit(code)) {
            return Option::None;
        }
        let digit: int = code - 48;
        // Checked before the multiply rather than after: after, it has already
        // wrapped and there is nothing left to notice.
        if (value > (parse_int_limit() - digit) / 10) {
            return Option::None;
        }
        value = value * 10 + digit;
        i = i + 1;
    }
    if (negative) {
        return Option::Some(0 - value);
    }
    return Option::Some(value);
}

// The same, refusing a sign. For places where a negative number is not a
// malformed input but a different mistake.
fn parse_uint(s: str): Option<int> {
    if (str_len(s) == 0) {
        return Option::None;
    }
    let first: int = str_char_at(s, 0);
    if (first == 45 || first == 43) {
        return Option::None;
    }
    return parse_int(s);
}

fn parse_bool(s: str): Option<bool> {
    if (s == "true") {
        return Option::Some(true);
    }
    if (s == "false") {
        return Option::Some(false);
    }
    return Option::None;
}

// Parse, or fall back. For the cases where a malformed input has an obvious
// answer and a match would be three lines saying so.
fn parse_int_or(s: str, fallback: int): int {
    return option_unwrap_or(parse_int(s), fallback);
}
