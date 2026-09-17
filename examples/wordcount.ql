// Counting words: the script the breadth work was for.
//
// Splitting, a hash map, a set, Option, and function values, in one pass over a
// piece of text. Nothing here is a special case in the compiler -- Map<str,int>
// and Set<str> are instantiations of library code, and the map carries
// hash_str as an ordinary function value because a type parameter has no
// bounds to derive a hash from.

include "std/map.ql";
include "std/set.ql";
include "std/string.ql";

fn text(): str {
    return "the quick brown fox jumps over the lazy dog "
         + "the dog barks and the fox runs";
}

fn is_common(word: str): bool {
    return word == "the" || word == "and" || word == "over";
}

fn main(): int {
    let counts: Map<str, int> = map_new(16, hash_str);
    let seen: Set<str> = set_new(16, hash_str);

    let words: Array<str> = str_split(text(), 32);   // ' '
    for (let i = 0; i < array_len(words); i = i + 1) {
        let word: str = words[i];
        if (str_len(word) == 0 || is_common(word)) {
            continue;
        }
        // The map's own entry, or zero if this is the first time.
        map_set(counts, word, map_get_or(counts, word, 0) + 1);
        set_add(seen, word);
    }

    println("-- totals --");
    println(array_len(words));
    println(map_len(counts));
    println(set_len(seen));

    println("-- repeated --");
    // Slot order is not insertion order, so the report is sorted by walking
    // the counts rather than by trusting the map to hand them back in order.
    let keys: Array<str> = map_keys(counts);
    for (let n = 4; n > 1; n = n - 1) {
        for (let i = 0; i < array_len(keys); i = i + 1) {
            if (map_get_or(counts, keys[i], 0) == n) {
                print(keys[i]);
                print(" ");
                println(n);
            }
        }
    }

    println("-- lookups --");
    match (map_get(counts, "fox")) {
        Option::Some(n) => { println(n); }
        Option::None => { println("not seen"); }
    }
    match (map_get(counts, "cat")) {
        Option::Some(n) => { println(n); }
        Option::None => { println("not seen"); }
    }

    println("-- set algebra --");
    let animals: Set<str> = set_new(8, hash_str);
    set_add(animals, "fox");
    set_add(animals, "dog");
    set_add(animals, "cat");
    println(set_len(set_intersection(animals, seen)));
    println(str_join(set_items(set_difference(animals, seen)), ","));

    return 0;
}
