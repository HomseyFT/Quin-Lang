// Functions as values: a function's name, in a position that is not a call,
// is a value naming that function.
//
// A function value is one word holding an index into the program's function
// table. It is not a heap reference, so it allocates nothing and the collector
// never traces one -- and that is the same reason there is no capture: a value
// carrying captured state would have to live on the heap like any other object.

include "std/list.ql";

fn add(a: int, b: int): int { return a + b; }
fn mul(a: int, b: int): int { return a * b; }

// A function taken as a parameter. Which one arrives is not known here.
fn fold(head: IntList, seed: int, op: fn(int, int): int): int {
    let total: int = seed;
    let cur: IntList = head;
    while (cur != null) {
        total = op(total, cur.value);
        cur = cur.next;
    }
    return total;
}

// A dispatch table: the choice is made once and stored, rather than being an
// if-chain at every use.
struct Operator {
    name: str,
    apply: fn(int, int): int,
}

fn double(n: int): int { return n * 2; }
fn is_odd(n: int): bool { return n % 2 != 0; }
fn show(n: int): void { print(n); print(" "); }

fn main(): int {
    let xs: IntList = list_push(list_push(list_push(list_empty(), 3), 2), 1);
    list_print(xs);
    println("");

    println(fold(xs, 0, add));   // 6
    println(fold(xs, 1, mul));   // 6

    // Returned from a function, stored in a variable, then called through it.
    let chosen: fn(int, int): int = add;
    println(chosen(20, 22));     // 42

    let plus: Operator = Operator { name: "+", apply: add };
    let times: Operator = Operator { name: "*", apply: mul };
    print(plus.name);
    print(" and ");
    println(times.name);

    // A field is not callable directly -- a call names a variable, not an
    // expression -- so it goes through one first.
    let op: fn(int, int): int = times.apply;
    println(op(6, 7));           // 42

    list_println(list_map(xs, double));
    list_println(list_filter(xs, is_odd));
    list_foreach(xs, show);
    println("");
    return 0;
}
