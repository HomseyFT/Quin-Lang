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
//     include "std/parse.ql";    // parse_int and friends, returning Option
//     include "std/fs.ql";       // files, as Results
//
// std/vec.ql and std/list.ql each include std/option.ql, for their try_get.
// std/parse.ql and std/fs.ql declare no type themselves but include ones that
// do, which reaches the same result: a name taken out of a program's hands.

include "std/math.ql";
include "std/bits.ql";
include "std/io.ql";
include "std/string.ql";
