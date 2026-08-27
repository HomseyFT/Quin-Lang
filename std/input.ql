// QuinLang Standard Library: reading input.
//
// Deliberately not in the prelude. This module declares an enum, and an enum
// name is global once included -- the same reason std/list.ql and std/vec.ql
// are left out of it. Include this one when you want it:
//
//     include "std/input.ql";

// What a read produced. The alternative is a str plus a rule about which empty
// string means end of input, and a rule is something you can forget; a variant
// you must account for is not.
enum Input {
    Line(str),
    End,
}

// A copy of `s` with one trailing line terminator removed -- "\n" or "\r\n",
// and nothing else.
//
// Not str_trim_end: that strips every trailing space, which for a line of
// input would silently discard characters the user typed.
fn strip_line_end(s: str): str {
    let n: int = str_len(s);
    if (n > 0) {
        if (str_char_at(s, n - 1) == 10) {
            n = n - 1;
        }
    }
    if (n > 0) {
        if (str_char_at(s, n - 1) == 13) {
            n = n - 1;
        }
    }
    return str_slice(s, 0, n);
}

// The next line of input without its terminator, or Input::End at end of input.
//
// The builtin read_line() keeps the terminator, which is what makes the two
// cases distinguishable: a blank line is "\n" and only end of input is "".
// This turns that distinction into something the type system checks.
fn next_line(): Input {
    let raw: str = read_line();
    if (str_len(raw) == 0) {
        return Input::End;
    }
    return Input::Line(strip_line_end(raw));
}
