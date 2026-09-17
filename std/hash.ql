// QuinLang Standard Library: hash functions, as values.
//
//     include "std/hash.ql";
//
// A hash must be **non-negative**, because the collections index with a mask
// against a power-of-two capacity and QuinLang's `%` keeps the sign of its left
// operand -- a negative hash would index backwards. Masking off the sign bit is
// what each of these does last.
//
// These are ordinary QuinLang, so hashing a key costs roughly a microsecond per
// character. That is fine for the sizes a 64 KiB heap holds and worth knowing
// before hashing a long key in a loop. Because a map carries its hash as a
// function value, a faster one can be substituted at the call that builds it
// without touching the map.
//
// This module declares no type, so unlike the collections that use it there is
// nothing stopping it from being in the prelude; it is left out only because
// they are.

// djb2, over the string's bytes.
fn hash_str(s: str): int {
    let h: int = 5381;
    for (let i = 0; i < str_len(s); i = i + 1) {
        h = h * 33 + str_char_at(s, i);
    }
    return h & 32767;
}

// A multiplicative scramble. An int key is often a small counter, and using it
// directly would put every key in a run of adjacent slots.
fn hash_int(n: int): int {
    let h: int = n * 2654;
    h = h ^ (h / 256);
    return h & 32767;
}

fn hash_bool(b: bool): int {
    if (b) {
        return 1;
    }
    return 0;
}
