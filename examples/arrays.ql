// Heap arrays: Array<T> is a fixed-length array of elements that lives on the
// heap rather than in a frame.
//
// The other array, int[N], lives in a frame. It cannot be returned, cannot be a
// field, and its length is part of its type. This one is an object: it is
// passed and returned by reference, survives the function that built it, and
// carries its length in its own heap header -- which is where the bounds check
// reads it from, and where the collector reads whether to trace it.

fn build_names(n: int): Array<str> {
    let names: Array<str> = array_new(n);
    for (let i = 0; i < n; i = i + 1) {
        names[i] = "row " + int_to_str(i);
    }
    return names;
}

fn total(values: Array<int>): int {
    let sum: int = 0;
    for (let i = 0; i < array_len(values); i = i + 1) {
        sum = sum + values[i];
    }
    return sum;
}

// An array is a reference, so this fills the caller's array rather than a copy.
fn fill_squares(values: Array<int>): void {
    for (let i = 0; i < array_len(values); i = i + 1) {
        values[i] = i * i;
    }
}

struct Table {
    title: str,
    rows: Array<str>,
}

fn main(): int {
    let squares: Array<int> = array_new(6);
    fill_squares(squares);
    println(total(squares));

    // The frame that built these strings is long gone, and the only thing
    // keeping them alive is the array holding them. A collection here moves
    // every one of them and rewrites the elements that point at them.
    let names: Array<str> = build_names(3);
    gc();
    for (let i = 0; i < array_len(names); i = i + 1) {
        println(names[i]);
    }

    // An array as a field, traced like any other reference the struct holds.
    let t: Table = Table { title: "report", rows: names };
    println(t.title);
    println(t.rows[1]);

    // Arrays nest, because an Array<T> is itself a one-word reference.
    let grid: Array<Array<int>> = array_new(2);
    for (let r = 0; r < 2; r = r + 1) {
        let row: Array<int> = array_new(3);
        for (let c = 0; c < 3; c = c + 1) {
            row[c] = r * 3 + c;
        }
        grid[r] = row;
    }
    println(grid[1][2]);

    return 0;
}
