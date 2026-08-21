// QuinLang Standard Library: float helpers.
//
// A float is IEEE 754 single precision, so it carries about seven significant
// digits. int and float never mix implicitly; int_to_float and float_to_int
// are the only bridge, and float_to_int truncates toward zero.
//
// Not included in std/prelude.ql. The prelude is for the modules a program
// almost always wants, and a program that never mentions a float should not
// pay for these.

fn fabs(x: float): float {
    if (x < 0.0) {
        return 0.0 - x;
    }
    return x;
}

fn fmin(a: float, b: float): float {
    if (a < b) {
        return a;
    }
    return b;
}

fn fmax(a: float, b: float): float {
    if (a > b) {
        return a;
    }
    return b;
}

fn fsign(x: float): int {
    if (x > 0.0) {
        return 1;
    }
    if (x < 0.0) {
        return 0 - 1;
    }
    return 0;
}

// floor, ceil and round go through float_to_int, so their argument must be
// within the int range. Past that there is no answer to give, and returning
// the input unchanged would look like success.
fn float_range_ok(x: float): bool {
    return x >= 0.0 - 32768.0 && x <= 32767.0;
}

fn floor(x: float): float {
    if (!float_range_ok(x)) {
        panic("floor: value outside the int range");
    }
    // float_to_int truncates toward zero, which rounds the wrong way for a
    // negative number that is not already whole.
    let truncated: float = int_to_float(float_to_int(x));
    if (truncated > x) {
        return truncated - 1.0;
    }
    return truncated;
}

fn ceil(x: float): float {
    if (!float_range_ok(x)) {
        panic("ceil: value outside the int range");
    }
    let truncated: float = int_to_float(float_to_int(x));
    if (truncated < x) {
        return truncated + 1.0;
    }
    return truncated;
}

// Half away from zero, so round(0.5) is 1.0 and round(-0.5) is -1.0.
fn round(x: float): float {
    if (x < 0.0) {
        return 0.0 - floor(0.5 - x);
    }
    return floor(x + 0.5);
}

fn ftrunc(x: float): float {
    if (!float_range_ok(x)) {
        panic("ftrunc: value outside the int range");
    }
    return int_to_float(float_to_int(x));
}

// x to a non-negative integer power, by repeated multiplication. A negative
// exponent would need division and is rejected rather than silently treated
// as zero.
fn fpow(base: float, exponent: int): float {
    if (exponent < 0) {
        panic("fpow: negative exponent");
    }
    let result: float = 1.0;
    let i: int = 0;
    while (i < exponent) {
        result = result * base;
        i = i + 1;
    }
    return result;
}

// Whether two floats agree to within tolerance. Rounding makes exact equality
// the wrong test for most computed values: 0.1 + 0.2 is not 0.3.
fn fclose(a: float, b: float, tolerance: float): bool {
    return fabs(a - b) <= tolerance;
}
