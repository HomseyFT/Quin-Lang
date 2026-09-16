// Files: reading, writing, and failing without being stopped.
//
// The builtins are total. `file_read` returns "" whether the file was empty or
// unreadable, and `file_error()` says which -- the same bargain `read_line`
// makes by returning "" at end of input. That is right for a primitive and
// wrong for a program, so std/fs.ql turns the convention into a Result: a rule
// you have to remember becomes a variant you have to account for.
//
// Where files come from is not the interpreter's business. The VM reaches the
// filesystem through the same ProgramIO object that output goes to, so an
// embedder can supply a virtual tree, a sandbox that refuses everything, or --
// as the test suite does when it runs this file -- an in-memory filesystem.

include "std/fs.ql";
include "std/string.ql";

// A path in the working directory, removed before this program exits.
fn scratch(): str {
    return "example-scratch.txt";
}

fn report(label: str, r: Result<int, str>): void {
    print(label);
    print(": ");
    println(result_show(r, show_int, show_str));
}

fn main(): int {
    println("-- writing --");
    report("write ", fs_write(scratch(), "first line\n"));
    report("append", fs_append(scratch(), "second line\n"));
    println(fs_exists(scratch()));

    println("-- reading --");
    match (fs_read(scratch())) {
        Result::Ok(text) => {
            print(text);
            println(str_len(text));
        }
        Result::Err(why) => { println("could not read: " + why); }
    }

    println("-- bytes --");
    // Content that is not text goes through Array<int>, one element per byte.
    let raw: Array<int> = array_new(3);
    raw[0] = 81;    // Q
    raw[1] = 76;    // L
    raw[2] = 10;
    report("bytes ", fs_write_bytes(scratch(), raw));
    match (fs_read_bytes(scratch())) {
        Result::Ok(data) => {
            println(array_len(data));
            println(data[0]);
        }
        Result::Err(why) => { println("could not read: " + why); }
    }

    println("-- failing --");
    // A missing file is a value, not a fault: the program decides what to do.
    match (fs_read("no-such-file.txt")) {
        Result::Ok(text) => { println("unexpectedly read something"); }
        Result::Err(why) => { println("read failed, and we are still here"); }
    }
    println(fs_read_or("no-such-file.txt", "(a default)"));
    println(fs_exists("no-such-file.txt"));

    println("-- cleaning up --");
    report("delete", fs_delete(scratch()));
    println(fs_exists(scratch()));
    // Deleting it twice fails, which is the point: it says so rather than
    // pretending.
    println(result_is_err(fs_delete(scratch())));

    return 0;
}
