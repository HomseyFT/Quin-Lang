// QuinLang Standard Library: bit manipulation on 16-bit ints.
//
// Bit 0 is the least significant; bit 15 is the sign bit. Two things about the
// language shape the code here:
//
//   - `>>` is an arithmetic shift, so it copies the sign bit downward. Every
//     bit extraction therefore masks with `& 1` rather than trusting the shift.
//   - `&` binds *looser* than `==`, so `x & 1 == 1` would parse as
//     `x & (1 == 1)` and fail to typecheck. The masks below are parenthesised.

fn bit_width(): int {
    return 16;
}

fn check_index(n: int): void {
    if (n < 0 || n > 15) {
        panic("bit index out of range: expected 0..15");
    }
}

// True when bit n of x is set.
fn bit_get(x: int, n: int): bool {
    check_index(n);
    return ((x >> n) & 1) == 1;
}

fn bit_set(x: int, n: int): int {
    check_index(n);
    return x | (1 << n);
}

fn bit_clear(x: int, n: int): int {
    check_index(n);
    return x & ~(1 << n);
}

fn bit_toggle(x: int, n: int): int {
    check_index(n);
    return x ^ (1 << n);
}

// How many bits of x are set.
fn popcount(x: int): int {
    let count: int = 0;
    for (let i = 0; i < 16; i = i + 1) {
        if (((x >> i) & 1) == 1) {
            count = count + 1;
        }
    }
    return count;
}

// x with its bit order reversed: bit 0 becomes bit 15, and so on.
fn reverse_bits(x: int): int {
    let result: int = 0;
    for (let i = 0; i < 16; i = i + 1) {
        result = (result << 1) | ((x >> i) & 1);
    }
    return result;
}

// Zero bits above the highest set bit. leading_zeros(0) is 16.
fn leading_zeros(x: int): int {
    for (let i = 15; i >= 0; i = i - 1) {
        if (((x >> i) & 1) == 1) {
            return 15 - i;
        }
    }
    return 16;
}

// Zero bits below the lowest set bit. trailing_zeros(0) is 16.
fn trailing_zeros(x: int): int {
    for (let i = 0; i < 16; i = i + 1) {
        if (((x >> i) & 1) == 1) {
            return i;
        }
    }
    return 16;
}

// Position of the highest set bit, or -1 when x is zero.
fn highest_bit(x: int): int {
    if (x == 0) {
        return 0 - 1;
    }
    return 15 - leading_zeros(x);
}

fn rotate_left(x: int, n: int): int {
    let k: int = n % 16;
    if (k < 0) {
        k = k + 16;
    }
    if (k == 0) {
        return x;
    }
    // The low part comes from the top k bits, masked because `>>` sign-extends.
    let low: int = (x >> (16 - k)) & ((1 << k) - 1);
    return (x << k) | low;
}

fn rotate_right(x: int, n: int): int {
    let k: int = n % 16;
    if (k < 0) {
        k = k + 16;
    }
    if (k == 0) {
        return x;
    }
    return rotate_left(x, 16 - k);
}

// x shifted right without sign extension, so the vacated bits are zero.
fn logical_shift_right(x: int, n: int): int {
    if (n < 0 || n > 15) {
        panic("shift count out of range: expected 0..15");
    }
    if (n == 0) {
        return x;
    }
    return (x >> n) & ((1 << (16 - n)) - 1);
}
