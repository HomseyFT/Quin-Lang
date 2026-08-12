// QuinLang Standard Library: a growable array of ints.
//
// The elements live in a raw heap block rather than an int[N], because arrays
// are frame-local and cannot cross a function boundary. The IntVec itself is a
// struct, so it is a reference: push and set modify the caller's vector rather
// than a copy, and a reallocation is invisible to the caller.
//
// The collector understands all of this. `data` is a heapptr field, so it is
// traced and rewritten if the block moves during a collection, including one
// triggered by the very allocation that grows the vector.

struct IntVec {
    data: heapptr,
    len: int,
    cap: int,
}

fn vec_new(capacity: int): IntVec {
    if (capacity <= 0) {
        panic("vec_new needs a capacity of at least 1");
    }
    // Two bytes a slot, and the product must stay inside a 16-bit int.
    if (capacity > 16000) {
        panic("vec_new capacity is too large");
    }
    return IntVec { data: alloc(capacity * 2), len: 0, cap: capacity };
}

fn vec_len(v: IntVec): int {
    return v.len;
}

fn vec_capacity(v: IntVec): int {
    return v.cap;
}

fn vec_is_empty(v: IntVec): bool {
    return v.len == 0;
}

fn vec_get(v: IntVec, index: int): int {
    if (index < 0 || index >= v.len) {
        panic("vec_get index out of range");
    }
    return heap_load(v.data + index * 2);
}

fn vec_set(v: IntVec, index: int, value: int): void {
    if (index < 0 || index >= v.len) {
        panic("vec_set index out of range");
    }
    heap_store(v.data + index * 2, value);
}

// Double the vector's capacity, copying the elements across. Reading v.data
// inside the loop matters: the allocation above may have triggered a
// collection, which would have moved the block and updated this field.
fn vec_grow(v: IntVec): void {
    let new_cap: int = v.cap * 2;
    if (new_cap <= v.cap || new_cap > 16000) {
        panic("vec capacity overflow");
    }
    let fresh: heapptr = alloc(new_cap * 2);
    for (let i = 0; i < v.len; i = i + 1) {
        heap_store(fresh + i * 2, heap_load(v.data + i * 2));
    }
    v.data = fresh;
    v.cap = new_cap;
}

fn vec_push(v: IntVec, value: int): void {
    if (v.len == v.cap) {
        vec_grow(v);
    }
    heap_store(v.data + v.len * 2, value);
    v.len = v.len + 1;
}

fn vec_pop(v: IntVec): int {
    if (v.len == 0) {
        panic("vec_pop called on an empty vector");
    }
    v.len = v.len - 1;
    return heap_load(v.data + v.len * 2);
}

fn vec_last(v: IntVec): int {
    if (v.len == 0) {
        panic("vec_last called on an empty vector");
    }
    return heap_load(v.data + (v.len - 1) * 2);
}

// Forget the contents without releasing the block, so the capacity is reused.
fn vec_clear(v: IntVec): void {
    v.len = 0;
}

fn vec_sum(v: IntVec): int {
    let total: int = 0;
    for (let i = 0; i < v.len; i = i + 1) {
        total = total + heap_load(v.data + i * 2);
    }
    return total;
}

fn vec_contains(v: IntVec, value: int): bool {
    for (let i = 0; i < v.len; i = i + 1) {
        if (heap_load(v.data + i * 2) == value) {
            return true;
        }
    }
    return false;
}

fn vec_index_of(v: IntVec, value: int): int {
    for (let i = 0; i < v.len; i = i + 1) {
        if (heap_load(v.data + i * 2) == value) {
            return i;
        }
    }
    return 0 - 1;
}

fn vec_reverse(v: IntVec): void {
    let i: int = 0;
    let j: int = v.len - 1;
    while (i < j) {
        let a: int = heap_load(v.data + i * 2);
        let b: int = heap_load(v.data + j * 2);
        heap_store(v.data + i * 2, b);
        heap_store(v.data + j * 2, a);
        i = i + 1;
        j = j - 1;
    }
}

fn vec_print(v: IntVec): void {
    print("[");
    for (let i = 0; i < v.len; i = i + 1) {
        print(heap_load(v.data + i * 2));
        if (i + 1 < v.len) {
            print(", ");
        }
    }
    print("]");
}

fn vec_println(v: IntVec): void {
    vec_print(v);
    println("");
}
