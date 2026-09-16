// QuinLang Standard Library: files, as values rather than as conventions.
//
//     include "std/fs.ql";
//
// The builtins underneath are total: file_read returns "" whether the file was
// empty or unreadable, and file_error() says which. That is the same bargain
// read_line makes by returning "" at end of input, and it is the right one for
// a primitive -- but a rule you have to remember is a rule you will forget.
//
// So this does for files what std/input.ql does for stdin: turns the convention
// into a type. A Result you have to match is a failure you cannot walk past.

include "std/result.ql";

// The reason the last file operation failed, as a Result. Every wrapper below
// is this shape: do the thing, then ask.
fn fs_check<T>(value: T): Result<T, str> {
    let why: str = file_error();
    if (str_len(why) > 0) {
        return Result::Err(why);
    }
    return Result::Ok(value);
}

fn fs_read(path: str): Result<str, str> {
    return fs_check(file_read(path));
}

fn fs_read_bytes(path: str): Result<Array<int>, str> {
    return fs_check(file_read_bytes(path));
}

// Ok carries the number of bytes written, which is the one fact about a
// successful write worth having.
fn fs_write(path: str, contents: str): Result<int, str> {
    file_write(path, contents);
    return fs_check(str_len(contents));
}

fn fs_append(path: str, contents: str): Result<int, str> {
    file_append(path, contents);
    return fs_check(str_len(contents));
}

fn fs_write_bytes(path: str, data: Array<int>): Result<int, str> {
    file_write_bytes(path, data);
    return fs_check(array_len(data));
}

fn fs_delete(path: str): Result<int, str> {
    file_delete(path);
    return fs_check(0);
}

// Not a Result: a file not being there is an answer, not a failure.
fn fs_exists(path: str): bool {
    return file_exists(path);
}

// Read a file, falling back rather than failing. For the cases where a missing
// file is a legitimate state -- a config that has not been written yet.
fn fs_read_or(path: str, fallback: str): str {
    return result_unwrap_or(fs_read(path), fallback);
}
