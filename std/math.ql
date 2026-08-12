// QuinLang Standard Library: integer math.
//
// Every value here is a 16-bit signed int, so results wrap at -32768..32767
// exactly as they do anywhere else in the language. Where a function cannot
// give a sensible answer it panics rather than returning a plausible wrong one.

fn abs(x: int): int {
    if (x < 0) {
        return 0 - x;
    }
    return x;
}

fn min(a: int, b: int): int {
    if (a < b) {
        return a;
    }
    return b;
}

fn max(a: int, b: int): int {
    if (a > b) {
        return a;
    }
    return b;
}

fn clamp(x: int, lo: int, hi: int): int {
    if (lo > hi) {
        panic("clamp called with lo greater than hi");
    }
    if (x < lo) {
        return lo;
    }
    if (x > hi) {
        return hi;
    }
    return x;
}

// -1, 0, or 1 according to the sign of x.
fn sign(x: int): int {
    if (x < 0) {
        return 0 - 1;
    }
    if (x > 0) {
        return 1;
    }
    return 0;
}

fn is_even(x: int): bool {
    return x % 2 == 0;
}

fn is_odd(x: int): bool {
    return !is_even(x);
}

// base raised to exp. The result wraps at 16 bits like any other
// multiplication, so pow(2, 15) is -32768 and pow(2, 16) is 0.
fn pow(base: int, exp: int): int {
    if (exp < 0) {
        panic("pow called with a negative exponent");
    }
    let result: int = 1;
    for (let i = 0; i < exp; i = i + 1) {
        result = result * base;
    }
    return result;
}

// Greatest common divisor, always non-negative. gcd(0, 0) is 0.
fn gcd(a: int, b: int): int {
    let x: int = abs(a);
    let y: int = abs(b);
    while (y != 0) {
        let t: int = x % y;
        x = y;
        y = t;
    }
    return x;
}

// Lowest common multiple. Wraps if the true result exceeds 16 bits.
fn lcm(a: int, b: int): int {
    if (a == 0 || b == 0) {
        return 0;
    }
    let g: int = gcd(a, b);
    return abs(a / g * b);
}

// Integer square root: the largest r with r * r <= x.
fn isqrt(x: int): int {
    if (x < 0) {
        panic("isqrt called with a negative number");
    }
    // 181 is the largest root that fits: 181 * 181 is 32761, and squaring
    // anything larger would overflow and start comparing nonsense.
    let r: int = 0;
    while (r < 181) {
        if ((r + 1) * (r + 1) > x) {
            return r;
        }
        r = r + 1;
    }
    return r;
}
