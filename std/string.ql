// QuinLang Standard Library: string helpers.
//
// A string is a heap object, so the ones built here are ordinary allocations
// that the collector reclaims when they go out of scope. Characters are bytes:
// str_char_at gives a code in 0..255, and char_to_str turns one back.
//
// Building a string a character at a time allocates once per character, since
// there is no mutable buffer. That is fine at these sizes and simple to read.

fn str_is_empty(s: str): bool {
    return str_len(s) == 0;
}

// The character code at index, or a panic if there is no such index.
fn str_at(s: str, index: int): int {
    return str_char_at(s, index);
}

fn str_first(s: str): int {
    if (str_is_empty(s)) {
        panic("str_first called on an empty string");
    }
    return str_char_at(s, 0);
}

fn str_last(s: str): int {
    if (str_is_empty(s)) {
        panic("str_last called on an empty string");
    }
    return str_char_at(s, str_len(s) - 1);
}

fn str_starts_with(s: str, prefix: str): bool {
    let n: int = str_len(prefix);
    if (n > str_len(s)) {
        return false;
    }
    for (let i = 0; i < n; i = i + 1) {
        if (str_char_at(s, i) != str_char_at(prefix, i)) {
            return false;
        }
    }
    return true;
}

fn str_ends_with(s: str, suffix: str): bool {
    let n: int = str_len(suffix);
    let base: int = str_len(s) - n;
    if (base < 0) {
        return false;
    }
    for (let i = 0; i < n; i = i + 1) {
        if (str_char_at(s, base + i) != str_char_at(suffix, i)) {
            return false;
        }
    }
    return true;
}

// The index where needle first occurs in s, or -1.
fn str_index_of(s: str, needle: str): int {
    let n: int = str_len(needle);
    let limit: int = str_len(s) - n;
    for (let start = 0; start <= limit; start = start + 1) {
        let matched: bool = true;
        for (let i = 0; i < n; i = i + 1) {
            if (str_char_at(s, start + i) != str_char_at(needle, i)) {
                matched = false;
                break;
            }
        }
        if (matched) {
            return start;
        }
    }
    return 0 - 1;
}

fn str_last_index_of(s: str, needle: str): int {
    let n: int = str_len(needle);
    for (let start = str_len(s) - n; start >= 0; start = start - 1) {
        let matched: bool = true;
        for (let i = 0; i < n; i = i + 1) {
            if (str_char_at(s, start + i) != str_char_at(needle, i)) {
                matched = false;
                break;
            }
        }
        if (matched) {
            return start;
        }
    }
    return 0 - 1;
}

fn str_contains(s: str, needle: str): bool {
    return str_index_of(s, needle) >= 0;
}

fn str_index_of_char(s: str, code: int): int {
    for (let i = 0; i < str_len(s); i = i + 1) {
        if (str_char_at(s, i) == code) {
            return i;
        }
    }
    return 0 - 1;
}

fn str_count_char(s: str, code: int): int {
    let n: int = 0;
    for (let i = 0; i < str_len(s); i = i + 1) {
        if (str_char_at(s, i) == code) {
            n = n + 1;
        }
    }
    return n;
}

fn str_repeat(s: str, times: int): str {
    if (times < 0) {
        panic("str_repeat called with a negative count");
    }
    let out: str = "";
    for (let i = 0; i < times; i = i + 1) {
        out = out + s;
    }
    return out;
}

fn str_reverse(s: str): str {
    let out: str = "";
    for (let i = str_len(s) - 1; i >= 0; i = i - 1) {
        out = out + char_to_str(str_char_at(s, i));
    }
    return out;
}

// -- character predicates, on codes rather than one-character strings --------

fn is_digit(code: int): bool {
    return code >= 48 && code <= 57;
}

fn is_upper(code: int): bool {
    return code >= 65 && code <= 90;
}

fn is_lower(code: int): bool {
    return code >= 97 && code <= 122;
}

fn is_alpha(code: int): bool {
    return is_upper(code) || is_lower(code);
}

fn is_alnum(code: int): bool {
    return is_alpha(code) || is_digit(code);
}

fn is_space(code: int): bool {
    // space, tab, newline, carriage return
    return code == 32 || code == 9 || code == 10 || code == 13;
}

fn to_upper_char(code: int): int {
    if (is_lower(code)) {
        return code - 32;
    }
    return code;
}

fn to_lower_char(code: int): int {
    if (is_upper(code)) {
        return code + 32;
    }
    return code;
}

fn str_to_upper(s: str): str {
    let out: str = "";
    for (let i = 0; i < str_len(s); i = i + 1) {
        out = out + char_to_str(to_upper_char(str_char_at(s, i)));
    }
    return out;
}

fn str_to_lower(s: str): str {
    let out: str = "";
    for (let i = 0; i < str_len(s); i = i + 1) {
        out = out + char_to_str(to_lower_char(str_char_at(s, i)));
    }
    return out;
}

fn str_trim_start(s: str): str {
    let start: int = 0;
    while (start < str_len(s) && is_space(str_char_at(s, start))) {
        start = start + 1;
    }
    return str_slice(s, start, str_len(s));
}

fn str_trim_end(s: str): str {
    let end: int = str_len(s);
    while (end > 0 && is_space(str_char_at(s, end - 1))) {
        end = end - 1;
    }
    return str_slice(s, 0, end);
}

fn str_trim(s: str): str {
    return str_trim_start(str_trim_end(s));
}

// The decimal int a string spells, with an optional leading sign. Anything
// else panics rather than guessing. The result wraps at 16 bits, as any other
// arithmetic would.
fn str_parse_int(s: str): int {
    let n: int = str_len(s);
    if (n == 0) {
        panic("str_parse_int called on an empty string");
    }
    let i: int = 0;
    let negative: bool = false;
    if (str_char_at(s, 0) == 45) {          // '-'
        negative = true;
        i = 1;
    }
    if (str_char_at(s, 0) == 43) {          // '+'
        i = 1;
    }
    if (i == n) {
        panic("str_parse_int found a sign with no digits");
    }
    let value: int = 0;
    while (i < n) {
        let code: int = str_char_at(s, i);
        if (!is_digit(code)) {
            panic("str_parse_int found a character that is not a digit");
        }
        value = value * 10 + (code - 48);
        i = i + 1;
    }
    if (negative) {
        return 0 - value;
    }
    return value;
}
