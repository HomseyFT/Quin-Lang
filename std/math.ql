// QuinLang Standard Library: Math functions

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
    if (x < lo) {
        return lo;
    }
    if (x > hi) {
        return hi;
    }
    return x;
}