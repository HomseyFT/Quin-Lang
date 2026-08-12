// QuinLang Standard Library: the common helpers, in one include.
//
//     include "std/prelude.ql";
//
// This pulls in the modules that define only functions. The collection
// modules are deliberately left out: std/list.ql and std/vec.ql each declare a
// struct type, and a struct name is global once included, so including them
// unasked would take names out of a program's hands. Include those directly
// when you want them:
//
//     include "std/list.ql";
//     include "std/vec.ql";

include "std/math.ql";
include "std/bits.ql";
include "std/io.ql";
