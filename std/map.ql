// QuinLang Standard Library: a hash map.
//
//     include "std/map.ql";
//
// Open addressing with linear probing over three parallel arrays -- keys,
// values, and a state array saying whether each slot is empty, occupied, or a
// tombstone left by a removal. No allocation per entry, which matters on a
// 64 KiB heap, and the collector needs nothing new: keys and values are traced
// or not by what Array<K> and Array<V> are, and the state array never is.
//
// **The map carries its own hash.** A type parameter has no bounds, so nothing
// about K tells the map how to hash one -- it is supplied at construction and
// stored as a function value. Equality needs nothing supplied: `==` already
// works on any type parameter, meaning content for str and identity for a
// struct reference.
//
// Capacity is always a power of two, so a slot is found by masking rather than
// by a remainder. That is not only speed: `%` keeps the sign of its left
// operand, so a negative hash would index backwards.

include "std/option.ql";
include "std/hash.ql";

// Slot states. A tombstone is not an empty slot: a probe must walk through one,
// or every key that once collided with a removed one becomes unfindable.
fn map_empty_slot(): int { return 0; }
fn map_used_slot(): int { return 1; }
fn map_dead_slot(): int { return 2; }

struct Map<K, V> {
    keys: Array<K>,
    values: Array<V>,
    state: Array<int>,
    hash: fn(K): int,
    len: int,
    dead: int,          // tombstones, which count toward the load
    mask: int,
}

fn map_round_up(n: int): int {
    let size: int = 8;
    while (size < n) {
        let doubled: int = size * 2;
        if (doubled <= size) {
            panic("map capacity is too large");
        }
        size = doubled;
    }
    return size;
}

fn map_new<K, V>(capacity: int, hash: fn(K): int): Map<K, V> {
    let slots: int = map_round_up(capacity);
    return Map { keys: array_new(slots), values: array_new(slots),
                 state: array_new(slots), hash: hash,
                 len: 0, dead: 0, mask: slots - 1 };
}

fn map_of<K, V>(key: K, value: V, hash: fn(K): int): Map<K, V> {
    let m: Map<K, V> = map_new(8, hash);
    map_set(m, key, value);
    return m;
}

fn map_len<K, V>(m: Map<K, V>): int {
    return m.len;
}

fn map_is_empty<K, V>(m: Map<K, V>): bool {
    return m.len == 0;
}

fn map_capacity<K, V>(m: Map<K, V>): int {
    return m.mask + 1;
}

// The slot a key occupies, or 0 - 1. Stops at the first empty slot, walking
// through tombstones on the way -- which is the whole reason removal leaves
// one rather than emptying the slot.
fn map_slot_of<K, V>(m: Map<K, V>, key: K): int {
    let i: int = m.hash(key) & m.mask;
    while (m.state[i] != map_empty_slot()) {
        if (m.state[i] == map_used_slot() && m.keys[i] == key) {
            return i;
        }
        i = (i + 1) & m.mask;
    }
    return 0 - 1;
}

fn map_has<K, V>(m: Map<K, V>, key: K): bool {
    return map_slot_of(m, key) >= 0;
}

fn map_get<K, V>(m: Map<K, V>, key: K): Option<V> {
    let i: int = map_slot_of(m, key);
    if (i < 0) {
        return Option::None;
    }
    return Option::Some(m.values[i]);
}

fn map_get_or<K, V>(m: Map<K, V>, key: K, fallback: V): V {
    return option_unwrap_or(map_get(m, key), fallback);
}

// Rehouse every live entry in a table twice the size, dropping the tombstones.
// The load is what triggers this, and tombstones count toward it: a probe walks
// them, so a table full of them is as slow as a table full of entries.
fn map_grow<K, V>(m: Map<K, V>): void {
    let slots: int = (m.mask + 1) * 2;
    if (slots <= m.mask) {
        panic("map capacity overflow");
    }
    let old_keys: Array<K> = m.keys;
    let old_values: Array<V> = m.values;
    let old_state: Array<int> = m.state;
    m.keys = array_new(slots);
    m.values = array_new(slots);
    m.state = array_new(slots);
    m.mask = slots - 1;
    m.len = 0;
    m.dead = 0;
    for (let i = 0; i < array_len(old_state); i = i + 1) {
        if (old_state[i] == map_used_slot()) {
            map_set(m, old_keys[i], old_values[i]);
        }
    }
}

fn map_set<K, V>(m: Map<K, V>, key: K, value: V): void {
    // Grown before inserting, so there is always an empty slot to stop a probe.
    if ((m.len + m.dead + 1) * 4 > (m.mask + 1) * 3) {
        map_grow(m);
    }
    let i: int = m.hash(key) & m.mask;
    let reuse: int = 0 - 1;
    while (m.state[i] != map_empty_slot()) {
        if (m.state[i] == map_used_slot() && m.keys[i] == key) {
            m.values[i] = value;
            return;
        }
        // The first tombstone is where this key goes if it is not already
        // here -- but the search has to continue to find out.
        if (m.state[i] == map_dead_slot() && reuse < 0) {
            reuse = i;
        }
        i = (i + 1) & m.mask;
    }
    if (reuse >= 0) {
        i = reuse;
        m.dead = m.dead - 1;
    }
    m.keys[i] = key;
    m.values[i] = value;
    m.state[i] = map_used_slot();
    m.len = m.len + 1;
}

// Returns whether anything was there. The slot becomes a tombstone rather than
// empty, so probes that passed through it still reach what is beyond.
//
// The key and value stay in their arrays until the slot is reused or the map
// grows, so a removed reference is not collected immediately. Nothing can clear
// them: `null` is not assignable to a type parameter that might be `int`. It is
// the same bounded retention vec_clear has.
fn map_remove<K, V>(m: Map<K, V>, key: K): bool {
    let i: int = map_slot_of(m, key);
    if (i < 0) {
        return false;
    }
    m.state[i] = map_dead_slot();
    m.len = m.len - 1;
    m.dead = m.dead + 1;
    return true;
}

fn map_clear<K, V>(m: Map<K, V>): void {
    for (let i = 0; i < array_len(m.state); i = i + 1) {
        m.state[i] = map_empty_slot();
    }
    m.len = 0;
    m.dead = 0;
}

// The keys, in slot order -- which is not insertion order and changes when the
// map grows. Nothing about a hash map promises an order.
fn map_keys<K, V>(m: Map<K, V>): Array<K> {
    let out: Array<K> = array_new(m.len);
    let n: int = 0;
    for (let i = 0; i < array_len(m.state); i = i + 1) {
        if (m.state[i] == map_used_slot()) {
            out[n] = m.keys[i];
            n = n + 1;
        }
    }
    return out;
}

fn map_foreach<K, V>(m: Map<K, V>, f: fn(K, V): void): void {
    for (let i = 0; i < array_len(m.state); i = i + 1) {
        if (m.state[i] == map_used_slot()) {
            f(m.keys[i], m.values[i]);
        }
    }
}
