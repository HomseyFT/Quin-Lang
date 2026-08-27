// Sum types: a value that is one of several shapes, and a match that must
// account for every one of them.
//
// The point is the first function below. Without an enum, a divide by zero
// leaves a library two options: fault and stop the program, or return a
// sentinel the caller may forget to check. A Result is the third option --
// the failure is in the type, so the caller cannot read the answer without
// first saying what happens when there isn't one.

enum Result {
    Ok(int),
    DivideByZero,
    NotADigit(int),
}

fn checked_div(a: int, b: int): Result {
    if (b == 0) {
        return DivideByZero;
    }
    return Ok(a / b);
}

// The second failure carries the offending character, which is the other
// thing a sum type buys: a failure can say more than that it happened.
fn digit_value(c: int): Result {
    if (c < 48) {
        return NotADigit(c);
    }
    if (c > 57) {
        return NotADigit(c);
    }
    return Ok(c - 48);
}

fn report(label: str, r: Result): int {
    print(label);
    print(": ");
    match (r) {
        Ok(value) => {
            println(value);
        }
        DivideByZero => {
            println("divided by zero");
        }
        NotADigit(c) => {
            print("'");
            print(char_to_str(c));
            println("' is not a digit");
        }
    }
    return 0;
}

// A variant carrying nothing is a constant: every `Nil` in a program is the
// same object, so building a list allocates only the links that hold values.
enum List {
    Nil,
    Cons(int, List),
}

fn sum(l: List): int {
    match (l) {
        Nil => {
            return 0;
        }
        Cons(head, rest) => {
            return head + sum(rest);
        }
    }
}

fn length(l: List): int {
    match (l) {
        Nil => {
            return 0;
        }
        Cons(head, rest) => {
            return 1 + length(rest);
        }
    }
}

fn main(): int {
    report("10 / 2", checked_div(10, 2));
    report("10 / 0", checked_div(10, 0));

    report("digit '7'", digit_value(str_char_at("7", 0)));
    report("digit 'x'", digit_value(str_char_at("x", 0)));

    // A match need not name every variant when `_` stands for the rest.
    let outcome: Result = checked_div(9, 0);
    match (outcome) {
        Ok(value) => {
            println(value);
        }
        _ => {
            println("something went wrong");
        }
    }

    let l: List = Cons(4, Cons(8, Cons(15, Nil)));
    print("sum: ");
    println(sum(l));
    print("length: ");
    println(length(l));

    return 0;
}
