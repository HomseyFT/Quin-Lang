// QuinLang Standard Library: a singly linked list of ints.
//
// Arrays cannot be parameters or return types, so a collection that crosses a
// function boundary has to be built from structs. A list is a reference, and
// the empty list is null.
//
// The list is persistent at the front: list_push returns a new head and leaves
// the old one usable as the tail it now shares.

struct IntList {
    value: int,
    next: IntList,
}

fn list_empty(): IntList {
    return null;
}

fn list_is_empty(head: IntList): bool {
    return head == null;
}

// A new head holding value, followed by the existing list.
fn list_push(head: IntList, value: int): IntList {
    return IntList { value: value, next: head };
}

fn list_len(head: IntList): int {
    let count: int = 0;
    let cur: IntList = head;
    while (cur != null) {
        count = count + 1;
        cur = cur.next;
    }
    return count;
}

fn list_head(head: IntList): int {
    if (head == null) {
        panic("list_head called on an empty list");
    }
    return head.value;
}

fn list_tail(head: IntList): IntList {
    if (head == null) {
        panic("list_tail called on an empty list");
    }
    return head.next;
}

fn list_get(head: IntList, index: int): int {
    if (index < 0) {
        panic("list_get called with a negative index");
    }
    let cur: IntList = head;
    let i: int = 0;
    while (cur != null) {
        if (i == index) {
            return cur.value;
        }
        i = i + 1;
        cur = cur.next;
    }
    panic("list_get index past the end of the list");
}

fn list_last(head: IntList): int {
    if (head == null) {
        panic("list_last called on an empty list");
    }
    let cur: IntList = head;
    while (cur.next != null) {
        cur = cur.next;
    }
    return cur.value;
}

fn list_sum(head: IntList): int {
    let total: int = 0;
    let cur: IntList = head;
    while (cur != null) {
        total = total + cur.value;
        cur = cur.next;
    }
    return total;
}

fn list_contains(head: IntList, value: int): bool {
    let cur: IntList = head;
    while (cur != null) {
        if (cur.value == value) {
            return true;
        }
        cur = cur.next;
    }
    return false;
}

fn list_index_of(head: IntList, value: int): int {
    let cur: IntList = head;
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

// A new list with the elements in the opposite order. The original is
// unchanged, since nothing here is modified in place.
fn list_reverse(head: IntList): IntList {
    let out: IntList = null;
    let cur: IntList = head;
    while (cur != null) {
        out = IntList { value: cur.value, next: out };
        cur = cur.next;
    }
    return out;
}

fn list_max(head: IntList): int {
    if (head == null) {
        panic("list_max called on an empty list");
    }
    let best: int = head.value;
    let cur: IntList = head.next;
    while (cur != null) {
        if (cur.value > best) {
            best = cur.value;
        }
        cur = cur.next;
    }
    return best;
}

fn list_min(head: IntList): int {
    if (head == null) {
        panic("list_min called on an empty list");
    }
    let best: int = head.value;
    let cur: IntList = head.next;
    while (cur != null) {
        if (cur.value < best) {
            best = cur.value;
        }
        cur = cur.next;
    }
    return best;
}

fn list_print(head: IntList): void {
    print("[");
    let cur: IntList = head;
    while (cur != null) {
        print(cur.value);
        if (cur.next != null) {
            print(", ");
        }
        cur = cur.next;
    }
    print("]");
}

fn list_println(head: IntList): void {
    list_print(head);
    println("");
}
