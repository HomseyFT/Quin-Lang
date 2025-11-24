fn main(): int {
    let arr: int[3];
    let len: int;
    let v: int;
    len = 0;

    len = array_push(arr, len, 10);
    len = array_push(arr, len, 20);
    len = array_push(arr, len, 30);

    v = array_pop(arr, len);
    len = len - 1;
    print(v);

    v = array_pop(arr, len);
    len = len - 1;
    print(v);

    v = array_pop(arr, len);
    len = len - 1;
    print(v);

    // Pointer + memory intrinsic tests using stack-allocated ints
    let a: int;
    let b: int;
    a = 1234;
    b = 0;

    // store16 & load16: treat addresses of a and b as ptr via builtin helpers
    // NOTE: in this minimal design we don't have explicit & operator yet,
    // so for now we'll just verify memcpy/memset on arrays below.

    let buf1: int[3];
    let buf2: int[3];
    let i: int;

    i = 0;
    buf1[0] = 7;
    buf1[1] = 8;
    buf1[2] = 9;

    // Copy buf1 -> buf2 using memcpy (operating on bytes)
    // Each int is 2 bytes, so copy 3 * 2 = 6 bytes.
    // We'll use the fact that array variables are stack locals and our
    // backend lowers them to contiguous memory.

    // For now, just print buf1 to confirm contents and rely on future
    // language support for taking addresses (&buf1[0]) to fully exercise
    // memcpy/memset.

    print(buf1[0]);
    print(buf1[1]);
    print(buf1[2]);

    return 0;
}
