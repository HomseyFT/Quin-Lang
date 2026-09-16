// QuinLang Standard Library: the common helpers, in one include.
//
//     include "std/prelude.ql";
//
// This pulls in the modules that define only functions. The ones that declare
// a type are deliberately left out: a struct or enum name is global once
// included, so pulling them in unasked would take names out of a program's
// hands. Include those directly when you want them:
//
//     include "std/vec.ql";      // Vec<T>
//     include "std/list.ql";     // List<T>
//     include "std/option.ql";   // Option<T>
//     include "std/result.ql";   // Result<T, E>
//
// std/vec.ql and std/list.ql each include std/option.ql, for their try_get.

include "std/math.ql";
include "std/bits.ql";
include "std/io.ql";
include "std/string.ql";
