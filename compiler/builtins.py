from typing import Dict, List, Tuple

# Signatures are written as type *names*; sema maps them to concrete Type
# objects, so this module needs to know nothing about the type system.

BuiltinSig = Tuple[List[str], str]


# Which builtins may be named as a function value, rather than only called.
#
# A builtin has no entry in the function table -- it lowers to instructions at
# the call site -- so there is no index for a value to hold. The compiler
# synthesises a one-line wrapper for the ones listed here, and only for the ones
# a program actually uses that way, so nothing below costs a program anything
# until it hands one over.
#
# Written out rather than derived, because opting one in should be a decision.
# Two rules govern what may be here.
#
# A builtin qualifies when its entry in get_builtins() is its whole contract.
# That excludes array_push, array_pop, array_new and array_len: their real
# shapes are settled in sema -- an int[N] that cannot be a parameter, an
# element type that comes from context -- so there is no fixed signature to
# give a wrapper.
#
# The second rule is not encoded here at all, deliberately: a builtin whose
# signature mentions `ptr` cannot be a function value, because a ptr indexes
# the frame it was taken in and names a different slot in any other -- see
# is_frame_relative in compiler_types.py. sema applies that rule to whatever is
# listed, so load16, store16, memcpy and memset stay below and are refused by
# the rule rather than by a carve-out somebody has to remember to keep. A
# `heapptr` is a real address and means the same thing in every frame, so
# alloc, heap_load and heap_store are unaffected.
VALUE_BUILTINS = frozenset({
    # Conversions, which is what most higher-order code wants to pass.
    "int_to_str", "char_to_str", "float_to_str", "int_to_float", "float_to_int",
    # Strings.
    "str_len", "str_char_at", "str_slice",
    # Files.
    "file_read", "file_write", "file_append", "file_exists", "file_delete",
    "file_error", "file_read_bytes", "file_write_bytes",
    # Input and arguments.
    "read_line", "argc", "argv",
    # Constant-time primitives, which exist to be composed.
    "ct_eq", "ct_select",
    # Memory and lifecycle. The four frame-relative ones are refused by the
    # ptr rule, not by their absence here.
    "load16", "store16", "memcpy", "memset",
    "alloc", "heap_load", "heap_store", "gc", "panic",
})


def get_builtins() -> Dict[str, BuiltinSig]:
    return {
        "load16":   (["ptr"], "int"),
        "store16":  (["ptr", "int"], "void"),
        "memcpy":   (["ptr", "ptr", "int"], "void"),
        "memset":   (["ptr", "int", "int"], "void"),
        # Shape checking for these two happens in sema/codegen.
        "array_push": (["int", "int", "int"], "int"),
        "array_pop":  (["int", "int"], "int"),
        # Heap arrays. Their real signatures name the element type -- array_new
        # returns Array<T> and array_get yields T -- which this table has no way
        # to spell, so sema types them and these entries carry only the name and
        # the arity, exactly as array_push and array_pop do above. Reading and
        # writing elements is the a[i] syntax rather than a builtin.
        "array_new":  (["int"], "int"),
        "array_len":  (["int"], "int"),
        "ct_eq":      (["int", "int"], "bool"),
        # ct_select(mask, x, y) returns x when mask != 0, else y; mask is
        # meant to be 0 or 1.
        "ct_select":  (["int", "int", "int"], "int"),
        # 'heapptr' is a different address space from the frame-relative 'ptr'
        # that '&' produces.
        "alloc":      (["int"], "heapptr"),
        "heap_load":  (["heapptr"], "int"),
        "heap_store": (["heapptr", "int"], "void"),
        # Collection also happens on allocation failure; this asks for one at
        # a known point.
        "gc":         ([], "void"),
        # The only way to report a problem: without it a library function
        # given bad arguments has no way to complain.
        "panic":      (["str"], "void"),
        # Concatenation is the '+' operator rather than a builtin.
        "str_len":     (["str"], "int"),
        "str_char_at": (["str", "int"], "int"),
        "str_slice":   (["str", "int", "int"], "str"),
        "int_to_str":  (["int"], "str"),
        "char_to_str": (["int"], "str"),
        # int and float never convert implicitly, so these are the only bridge
        # between them. float_to_int truncates toward zero, like integer '/'.
        "int_to_float":  (["int"], "float"),
        "float_to_int":  (["float"], "int"),
        "float_to_str":  (["float"], "str"),
        # Input. read_line keeps the line's terminator, so "" is end of input
        # and a blank line is "\n"; std/input.ql wraps that in an enum for
        # code that would rather match than compare lengths.
        "read_line":  ([], "str"),
        # Files. Every one of these is total: a failure sets the reason that
        # file_error() reports and the program keeps going, the same bargain
        # read_line makes by returning "" at end of input. std/fs.ql turns that
        # into a Result, which is the version worth writing programs against.
        "file_read":        (["str"], "str"),
        "file_write":       (["str", "str"], "bool"),
        "file_append":      (["str", "str"], "bool"),
        "file_exists":      (["str"], "bool"),
        "file_delete":      (["str"], "bool"),
        "file_error":       ([], "str"),
        # The byte-oriented pair, for content that is not text. An Array<int>
        # needs nothing from sema: it resolves through type_from_name like any
        # other name, which is why the raw layer can stay free of std types.
        "file_read_bytes":  (["str"], "Array<int>"),
        "file_write_bytes": (["str", "Array<int>"], "bool"),
        # argc() counts what the host supplied, so a program cannot assume
        # argv(0) exists: the driver puts the program path there as C does, but
        # an embedded VM supplies whatever it likes, including nothing.
        "argc":       ([], "int"),
        "argv":       (["int"], "str"),
    }
