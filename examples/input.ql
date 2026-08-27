// Reading input, and arguments.
//
// Run it with a file on stdin and some arguments:
//
//     printf 'ada\ngrace\n' | python3 -m compiler.driver_vm examples/input.ql --greet
//
// The fixture in examples/input.in is what the golden test feeds it.

include "std/input.ql";
include "std/string.ql";

// read_line() is the primitive: it keeps the line's terminator, so "" means
// end of input and a blank line means "\n". next_line() wraps that in an enum
// so the two cases cannot be confused for one another.
fn count_lines(): int {
    let lines: int = 0;
    let blanks: int = 0;
    let longest: int = 0;

    while (true) {
        match (next_line()) {
            Input::Line(text) => {
                lines = lines + 1;
                if (str_len(text) == 0) {
                    blanks = blanks + 1;
                } else {
                    print("  ");
                    print(lines);
                    print(": ");
                    println(text);
                }
                if (str_len(text) > longest) {
                    longest = str_len(text);
                }
            }
            Input::End => {
                // The only way out. A blank line reaches the arm above, which
                // is the distinction the terminator convention preserves.
                break;
            }
        }
    }

    print("lines: ");
    println(lines);
    print("blank: ");
    println(blanks);
    print("longest: ");
    println(longest);
    return lines;
}

fn main(): int {
    // argc() counts whatever the host supplied. Run through the driver, that
    // is the program path followed by anything after it; run under a test
    // harness that passes none, it is zero. So a program indexes from 0 and
    // does not assume argv(0) is there.
    print("arguments: ");
    println(argc());
    for (let i = 0; i < argc(); i = i + 1) {
        print("  ");
        println(argv(i));
    }

    println("input:");
    count_lines();
    return 0;
}
