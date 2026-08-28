from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

@dataclass(frozen=True)
class Type:
    name: str
    size: int  # bytes

    def __str__(self) -> str:
        return self.name
Int = Type("int", 2)
Str = Type("str", 2)  # heap address of a string object
Void = Type("void", 0)
Bool = Type("bool", 1)
# IEEE 754 single precision. The only type wider than a word: it takes two
# consecutive slots wherever a value is stored, which is what word_count()
# below exists to express.
Float = Type("float", 4)

# Two disjoint address spaces, kept as separate types so a pointer into one
# cannot be dereferenced as if it belonged to the other:
#
#   ptr     - index into the current frame's locals, from '&'.
#             Read/written with load16/store16/memcpy/memset.
#   heapptr - byte offset into the VM's heap, from alloc().
#             Read/written with heap_load/heap_store.
#
# Both are 16-bit values, so nothing but the type system tells them apart;
# mixing them used to typecheck and silently read the wrong memory.
Ptr = Type("ptr", 2)
HeapPtr = Type("heapptr", 2)

# The type of the 'null' literal, which nobody can write down. It exists so
# null can initialize or be compared against any reference type without those
# types collapsing into one.
Null = Type("null", 2)

BUILTIN_TYPES: Dict[str, Type] = {
    "int": Int,
    "str": Str,
    "void": Void,
    "bool": Bool,
    "float": Float,
    "ptr": Ptr,
    "heapptr": HeapPtr,
}

ARRAY_PREFIX = "int["

# A function type is spelled fn(T, ...): R, and canonicalised to fn(T,...):R.
FUNC_PREFIX = "fn("


@dataclass(frozen=True)
class StructType(Type):
    """A reference to a heap-allocated struct: one word, like any other
    reference. The field layout lives in StructInfo instead, because Type is
    compared by value and two structs are the same type exactly when they
    share a name.

    Subclassing matters: a dataclass __eq__ requires both sides to be the same
    class, so StructType('Point', 2) never compares equal to Type('Point', 2).
    """


@dataclass(frozen=True)
class StructField:
    name: str
    type: Type
    offset: int  # in 16-bit words from the object's base address


@dataclass
class StructInfo:
    """A struct's declared layout, and the id its heap header carries."""
    name: str
    type_id: int
    fields: List[StructField] = field(default_factory=list)

    @property
    def word_size(self) -> int:
        return sum(word_count(f.type) for f in self.fields)

    def field_named(self, name: str) -> Optional[StructField]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def type(self) -> StructType:
        # Always one word: the size of a *reference*, not of the object, which
        # lives in word_size. That matters for recursion — resolving
        # `next: Node` builds Node's type while its field list is still empty,
        # so a size derived from the fields would not equal the completed one.
        return StructType(self.name, 2)


@dataclass(frozen=True)
class EnumType(Type):
    """A reference to one of an enum's variants: one word, like any other
    reference. Which variant it is lives in the object's heap header, where the
    collector already reads a type id -- so the tag costs nothing extra and the
    collector needs no changes to trace a variant's payload.

    Subclassed for the same reason StructType is: a dataclass __eq__ requires
    both sides to be the same class, so an enum named Point and a struct named
    Point stay distinct types.
    """


@dataclass
class VariantInfo(StructInfo):
    """One variant's layout. A variant *is* a struct at runtime: same header,
    same type id, same field offsets, allocated and traced the same way. The
    only additions are which enum it belongs to and where it sits in it.

    `name` is the qualified spelling, `Result::Ok`, because that is how it is
    written and how it should read back in a debugger. `short_name` is what
    follows the `::`, which is the part that must be unique within its enum.
    """
    enum_name: str = ""
    short_name: str = ""
    index: int = 0


@dataclass
class EnumInfo:
    """A named set of variants.

    An enum has no type id of its own -- there is never an object of type
    `Result`, only an `Ok` or an `Err` -- so ids belong to the variants, in the
    same space as struct ids because the collector indexes one table by them.
    """
    name: str
    variants: List[VariantInfo] = field(default_factory=list)

    def variant_named(self, qualified: str) -> Optional[VariantInfo]:
        """Looked up by the qualified name, which is what a pattern carries."""
        for v in self.variants:
            if v.name == qualified:
                return v
        return None

    def type(self) -> EnumType:
        return EnumType(self.name, 2)


@dataclass(frozen=True)
class FuncType(Type):
    """A reference to a named function: one word, holding its index in the
    program's function table.

    Deliberately *not* a heap reference. A function value names code, which
    neither moves nor is collected, so is_reference_type stays False for it and
    the collector never traces one. That is the whole reason the type is this
    cheap -- and the reason there is no capture: a value carrying captured
    state would have to live on the heap and be traced like any other object.

    Subclassed for the same reason StructType is: a dataclass __eq__ requires
    both sides to be the same class, so a struct named `fn(int):int` -- which
    nobody can declare, but the type system should not rely on that -- stays a
    distinct type. Equality is by `name`, which is canonical, so two spellings
    of one signature are one type.
    """
    params: Tuple[Type, ...] = ()
    ret: Type = Void

    def arity_matches(self, count: int) -> bool:
        return count == len(self.params)


def func_type(params, ret: Type) -> FuncType:
    """The FuncType for a signature, under its canonical spelling."""
    params = tuple(params)
    spelling = f"fn({','.join(p.name for p in params)}):{ret.name}"
    return FuncType(spelling, 2, params, ret)


def word_count(t: Type) -> int:
    """How many 16-bit slots a value of this type occupies.

    One for everything except float, which is 32 bits wide. Storage sizing goes
    through here rather than assuming one slot per value, so adding another
    wide type later does not mean hunting for the assumption again. Arrays are
    not values in this sense -- an int[N] is N slots of int, and array_length()
    answers that question.
    """
    return 2 if t == Float else 1


def is_func_type(t: Type) -> bool:
    return isinstance(t, FuncType)


def is_struct_type(t: Type) -> bool:
    return isinstance(t, StructType)


def is_enum_type(t: Type) -> bool:
    return isinstance(t, EnumType)


def is_reference_type(t: Type) -> bool:
    """Whether values of this type are heap addresses the GC must trace. A str
    counts: a str slot roots its string, and a str field must be traced."""
    return is_struct_type(t) or is_enum_type(t) or t == HeapPtr or t == Str


def is_nullable(t: Type) -> bool:
    """Whether null may stand in for a value of this type. Not the same
    question as is_reference_type: a string is a heap reference, but an
    uninitialised str is the empty string, so there is no null string."""
    return is_struct_type(t) or is_enum_type(t) or t == HeapPtr


def assignable(target: Type, value: Type) -> bool:
    """There are no implicit conversions; null initializing a reference is the
    single exception."""
    if target == value:
        return True
    return value == Null and is_nullable(target)


def comparable(left: Type, right: Type) -> bool:
    if left == right:
        return True
    return ((left == Null and is_nullable(right))
            or (right == Null and is_nullable(left)))


class UnknownTypeError(Exception):
    """Callers that know the source location should catch this and re-raise it
    as a SemanticError carrying line/col."""


def array_length_from_name(name: Optional[str]) -> Optional[int]:
    """N for a type name of the form 'int[N]', None if it isn't one. Raises
    UnknownTypeError if it looks like an array but N is missing, non-numeric,
    or non-positive."""
    if not isinstance(name, str) or not name.startswith(ARRAY_PREFIX) or not name.endswith("]"):
        return None
    inner = name[len(ARRAY_PREFIX):-1]
    try:
        n = int(inner)
    except ValueError:
        raise UnknownTypeError(f"Invalid array length '{inner}' in type '{name}'")
    if n <= 0:
        raise UnknownTypeError(f"Array length must be positive, got {n} in type '{name}'")
    return n


def split_top_level(text: str) -> List[str]:
    """Split on commas that are not inside a nested parameter list, so that
    `int,fn(int,int):int` is two parameters rather than three."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts]


def func_signature_from_name(name: Optional[str]):
    """(parameter type names, return type name) for a type of the form
    `fn(...)` or `fn(...):R`, None if it isn't one.

    Written as string surgery for the same reason array_length_from_name is:
    the parser hands types down as their spelling, so this is where a spelling
    becomes structure. Raises UnknownTypeError on a malformed one.
    """
    if not isinstance(name, str) or not name.startswith(FUNC_PREFIX):
        return None

    depth, close = 0, -1
    for i, c in enumerate(name[len(FUNC_PREFIX) - 1:], start=len(FUNC_PREFIX) - 1):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                close = i
                break
    if close < 0:
        raise UnknownTypeError(f"Unbalanced '(' in function type '{name}'")

    inner, rest = name[len(FUNC_PREFIX):close], name[close + 1:]
    if rest == "":
        ret_name = "void"       # an omitted return type is void, as it is on a declaration
    elif rest.startswith(":") and len(rest) > 1:
        ret_name = rest[1:]
    else:
        raise UnknownTypeError(f"Malformed function type '{name}'")

    params = [] if not inner.strip() else split_top_level(inner)
    if any(not p for p in params):
        raise UnknownTypeError(f"Empty parameter type in function type '{name}'")
    return params, ret_name


def type_from_name(name: str, structs: Optional[Dict[str, "StructInfo"]] = None,
                   enums: Optional[Dict[str, "EnumInfo"]] = None) -> Type:
    if not isinstance(name, str):
        raise UnknownTypeError(f"Invalid type name {name!r}")
    n = array_length_from_name(name)
    if n is not None:
        return Type(name, 2 * n)
    signature = func_signature_from_name(name)
    if signature is not None:
        param_names, ret_name = signature
        params = []
        for param_name in param_names:
            t = type_from_name(param_name, structs, enums)
            # The same two rules a declared parameter obeys, enforced here so a
            # signature that could never be satisfied cannot be written down.
            if t == Void:
                raise UnknownTypeError(f"'void' is not a parameter type in '{name}'")
            if is_array_type(t):
                raise UnknownTypeError(f"An array is not a parameter type in '{name}'")
            params.append(t)
        ret = type_from_name(ret_name, structs, enums)
        if is_array_type(ret):
            raise UnknownTypeError(f"An array is not a return type in '{name}'")
        return func_type(params, ret)
    if name in BUILTIN_TYPES:
        return BUILTIN_TYPES[name]
    if structs and name in structs:
        return structs[name].type()
    if enums and name in enums:
        return enums[name].type()
    raise UnknownTypeError(f"Unknown type '{name}'")


def is_array_type(t: Type) -> bool:
    return isinstance(t, Type) and t.name.startswith(ARRAY_PREFIX)


def array_length(t: Type) -> Optional[int]:
    return array_length_from_name(t.name) if isinstance(t, Type) else None
