// QuinLang Standard Library: a singly linked list of any element type.
//
//     include "std/list.ql";
//
// A list is a reference and the empty list is null, so there is no separate
// empty object. The list is persistent at the front: list_push returns a new
// head and leaves the old one usable as the tail it now shares.
//
// Vec<T> is the better default -- contiguous, indexable, one allocation for
// many elements. A list earns its place when the sharing does: pushing onto a
// list leaves every existing head valid, where pushing onto a vector does not.

include "std/option.ql";

struct List<T> {
    value: T,
    next: List<T>,
}

fn list_empty<T>(): List<T> {
    return null;
}

fn list_is_empty<T>(head: List<T>): bool {
    return head == null;
}

// Returns the new head. The old one stays valid as this one's tail.
fn list_push<T>(head: List<T>, value: T): List<T> {
    return List { value: value, next: head };
}

// A one-element list. Worth having because `null` on its own says nothing
// about what the list holds, so it cannot start a chain of pushes.
fn list_of<T>(value: T): List<T> {
    return List { value: value, next: null };
}

fn list_len<T>(head: List<T>): int {
    let n: int = 0;
    let cur: List<T> = head;
    while (cur != null) {
        n = n + 1;
        cur = cur.next;
    }
    return n;
}

fn list_head<T>(head: List<T>): T {
    if (head == null) {
        panic("list_head called on an empty list");
    }
    return head.value;
}

fn list_tail<T>(head: List<T>): List<T> {
    if (head == null) {
        panic("list_tail called on an empty list");
    }
    return head.next;
}

fn list_get<T>(head: List<T>, index: int): T {
    if (index < 0) {
        panic("list_get called with a negative index");
    }
    let cur: List<T> = head;
    let i: int = 0;
    while (cur != null) {
        if (i == index) {
            return cur.value;
        }
        i = i + 1;
        cur = cur.next;
    }
    panic("list_get index is past the end of the list");
}

fn list_try_get<T>(head: List<T>, index: int): Option<T> {
    let cur: List<T> = head;
    let i: int = 0;
    while (cur != null) {
        if (i == index) {
            return Option::Some(cur.value);
        }
        i = i + 1;
        cur = cur.next;
    }
    return Option::None;
}

fn list_last<T>(head: List<T>): T {
    if (head == null) {
        panic("list_last called on an empty list");
    }
    let cur: List<T> = head;
    while (cur.next != null) {
        cur = cur.next;
    }
    return cur.value;
}

fn list_contains<T>(head: List<T>, value: T): bool {
    let cur: List<T> = head;
    while (cur != null) {
        if (cur.value == value) {
            return true;
        }
        cur = cur.next;
    }
    return false;
}

fn list_index_of<T>(head: List<T>, value: T): int {
    let cur: List<T> = head;
    let i: int = 0;
    while (cur != null) {
        if (cur.value == value) {
            return i;
        }
        i = i + 1;
        cur = cur.next;
    }
    return 0 - 1;
}

// A new list, front to back. The original is untouched, as it is shared.
fn list_reverse<T>(head: List<T>): List<T> {
    let out: List<T> = null;
    let cur: List<T> = head;
    while (cur != null) {
        out = List { value: cur.value, next: out };
        cur = cur.next;
    }
    return out;
}

// -- higher order -----------------------------------------------------------
//
// Each of these builds forward with a tail pointer -- one node per element --
// rather than prepending and reversing, which would allocate twice as many.

fn list_map<T, U>(head: List<T>, f: fn(T): U): List<U> {
    let out: List<U> = null;
    let tail: List<U> = null;
    let cur: List<T> = head;
    while (cur != null) {
        let node: List<U> = List { value: f(cur.value), next: null };
        if (out == null) {
            out = node;
        } else {
            tail.next = node;
        }
        tail = node;
        cur = cur.next;
    }
    return out;
}

fn list_filter<T>(head: List<T>, keep: fn(T): bool): List<T> {
    let out: List<T> = null;
    let tail: List<T> = null;
    let cur: List<T> = head;
    while (cur != null) {
        if (keep(cur.value)) {
            let node: List<T> = List { value: cur.value, next: null };
            if (out == null) {
                out = node;
            } else {
                tail.next = node;
            }
            tail = node;
        }
        cur = cur.next;
    }
    return out;
}

fn list_fold<T, A>(head: List<T>, seed: A, op: fn(A, T): A): A {
    let total: A = seed;
    let cur: List<T> = head;
    while (cur != null) {
        total = op(total, cur.value);
        cur = cur.next;
    }
    return total;
}

fn list_foreach<T>(head: List<T>, f: fn(T): void): void {
    let cur: List<T> = head;
    while (cur != null) {
        f(cur.value);
        cur = cur.next;
    }
}

fn list_any<T>(head: List<T>, pred: fn(T): bool): bool {
    let cur: List<T> = head;
    while (cur != null) {
        if (pred(cur.value)) {
            return true;
        }
        cur = cur.next;
    }
    return false;
}

fn list_all<T>(head: List<T>, pred: fn(T): bool): bool {
    let cur: List<T> = head;
    while (cur != null) {
        if (!pred(cur.value)) {
            return false;
        }
        cur = cur.next;
    }
    return true;
}

fn list_show<T>(head: List<T>, show: fn(T): str): str {
    let out: str = "[";
    let cur: List<T> = head;
    while (cur != null) {
        out = out + show(cur.value);
        if (cur.next != null) {
            out = out + ", ";
        }
        cur = cur.next;
    }
    return out + "]";
}

// -- concrete where the element type is not free ----------------------------

fn list_sum(head: List<int>): int {
    let total: int = 0;
    let cur: List<int> = head;
    while (cur != null) {
        total = total + cur.value;
        cur = cur.next;
    }
    return total;
}

fn list_max(head: List<int>): int {
    if (head == null) {
        panic("list_max called on an empty list");
    }
    let best: int = head.value;
    let cur: List<int> = head.next;
    while (cur != null) {
        if (cur.value > best) {
            best = cur.value;
        }
        cur = cur.next;
    }
    return best;
}

fn list_min(head: List<int>): int {
    if (head == null) {
        panic("list_min called on an empty list");
    }
    let best: int = head.value;
    let cur: List<int> = head.next;
    while (cur != null) {
        if (cur.value < best) {
            best = cur.value;
        }
        cur = cur.next;
    }
    return best;
}
