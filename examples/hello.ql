fn main(): int {
    let arr: int[3];
    let len: int;
    len = 0;

    len = array_push(arr, len, 10);
    len = array_push(arr, len, 20);
    len = array_push(arr, len, 30);

    print(arr[0]);
    print(arr[1]);  // only two prints

    return 0;
}
