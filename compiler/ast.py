from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import Callable, List, Optional, Union

@dataclass
class Node:
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)

# Expressions
@dataclass
class Expr(Node):
    pass

@dataclass
class Literal(Expr):
    value: Union[int, float, str, bool, None]

@dataclass
class Identifier(Expr):
    name: str

@dataclass
class Unary(Expr):
    op: str
    right: Expr

@dataclass
class Binary(Expr):
    left: Expr
    op: str
    right: Expr

@dataclass
class Call(Expr):
    callee: str
    args: List[Expr]
    # The expression the call goes through, when it is not a name. Holds the
    # FieldAccess itself for `m.hash(key)`, so every pass reuses what it
    # already does with one. None for an ordinary call, which is why nothing
    # that dispatches on `callee` needed to change.
    receiver: Optional[Expr] = None
    # Type arguments written out, `f::<int, str>(x)`. Empty when the call names
    # no generic function, or when its type arguments are inferred -- which is
    # the usual case, so this is usually empty even for a generic call.
    type_args: List[str] = field(default_factory=list)

@dataclass
class Index(Expr):
    array: Expr
    index: Expr

@dataclass
class AddressOf(Expr):
    target: Expr  # Identifier or Index

@dataclass
class FieldAccess(Expr):
    obj: Expr
    field: str

@dataclass
class FieldInit(Node):
    name: str
    value: Expr

@dataclass
class StructLit(Expr):
    struct_name: str
    fields: List[FieldInit]

# Statements
@dataclass
class Stmt(Node):
    pass

@dataclass
class ExprStmt(Stmt):
    expr: Expr

@dataclass
class VarDecl(Stmt):
    name: str
    type_name: Optional[str]
    init: Optional[Expr]

@dataclass
class Assign(Stmt):
    target: Expr  # Identifier or Index
    value: Expr

@dataclass
class Print(Stmt):
    value: Expr

@dataclass
class PrintLn(Stmt):
    value: Expr

@dataclass
class Return(Stmt):
    value: Optional[Expr]

@dataclass
class VmAsm(Stmt):
    # Raw text: a line-based DSL that codegen lowers straight to bytecode.
    # No other pass looks inside it.
    code: str

@dataclass
class If(Stmt):
    cond: Expr
    then_block: List[Stmt]
    else_block: Optional[List[Stmt]] = None

@dataclass
class While(Stmt):
    cond: Expr
    body: List[Stmt]

@dataclass
class For(Stmt):
    # Any of init/cond/step may be omitted; an omitted cond loops forever.
    init: Optional[Stmt]
    cond: Optional[Expr]
    step: Optional[Stmt]
    body: List[Stmt]

@dataclass
class MatchArm(Node):
    """One arm of a match.

    `variant` is None for the catch-all `_`, which is why it is optional rather
    than a separate node: everything else about an arm is the same.
    `bindings` names the payload positionally and is empty for a variant that
    carries none.
    """
    variant: Optional[str]
    bindings: List[str]
    body: List[Stmt]

@dataclass
class Match(Stmt):
    subject: Expr
    arms: List[MatchArm]

@dataclass
class Break(Stmt):
    pass

@dataclass
class Continue(Stmt):
    pass

@dataclass
class Block(Stmt):
    stmts: List[Stmt] = field(default_factory=list)

@dataclass
class Param(Node):
    name: str
    type_name: str

@dataclass
class Function(Node):
    name: str
    params: List[Param]
    return_type: Optional[str]
    body: List[Stmt]
    # The names this declaration binds, `<T, U>`. Empty for an ordinary
    # declaration; a declaration with any is a template, instantiated per use
    # rather than compiled as written.
    type_params: List[str] = field(default_factory=list)
    # Which file declared it, stamped by the resolver when it merges includes.
    # A line number alone is ambiguous once a program spans files.
    source_file: str = field(default="", kw_only=True)

@dataclass
class FieldDef(Node):
    name: str
    type_name: str

@dataclass
class StructDef(Node):
    name: str
    fields: List[FieldDef]
    # The names this declaration binds, `<T, U>`. Empty for an ordinary
    # declaration; a declaration with any is a template, instantiated per use
    # rather than compiled as written.
    type_params: List[str] = field(default_factory=list)

@dataclass
class VariantDef(Node):
    name: str
    # Payload types by position. Empty for a variant that carries nothing,
    # which is stored as one interned instance rather than allocated per use.
    payload: List[str] = field(default_factory=list)

@dataclass
class EnumDef(Node):
    name: str
    variants: List[VariantDef]
    # The names this declaration binds, `<T, U>`. Empty for an ordinary
    # declaration; a declaration with any is a template, instantiated per use
    # rather than compiled as written.
    type_params: List[str] = field(default_factory=list)

@dataclass
class Include(Node):
    path: str

@dataclass
class Program(Node):
    includes: List[Include]
    functions: List[Function]
    structs: List[StructDef] = field(default_factory=list)
    enums: List[EnumDef] = field(default_factory=list)


# Which fields hold a type name rather than a variable, field or function name.
# Listed here, beside the declarations, so that adding a node carrying one is a
# change in this file and nowhere else.
_TYPE_NAME_FIELDS = {
    Param: ("type_name",),
    VarDecl: ("type_name",),
    FieldDef: ("type_name",),
    Function: ("return_type",),
    StructLit: ("struct_name",),
}

_TYPE_NAME_LISTS = {
    VariantDef: ("payload",),
    Call: ("type_args",),
}


def substitute_types(node: Node, rewrite: Callable[[str], str]) -> None:
    """Rewrite every type name in a tree, in place.

    This is the whole of what instantiating a declaration does to its body: a
    template is cloned and its type parameters replaced by what they were bound
    to. Nothing else is touched -- a variable named T stays named T, and a match
    arm still writes `Option::Some` whatever the enum was instantiated at,
    because which instantiation it means comes from the subject's type.
    """
    for cls, names in _TYPE_NAME_FIELDS.items():
        if isinstance(node, cls):
            for name in names:
                value = getattr(node, name)
                if value is not None:
                    setattr(node, name, rewrite(value))
    for cls, names in _TYPE_NAME_LISTS.items():
        if isinstance(node, cls):
            for name in names:
                setattr(node, name, [rewrite(v) for v in getattr(node, name)])

    for f in fields(node):
        value = getattr(node, f.name)
        if isinstance(value, Node):
            substitute_types(value, rewrite)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Node):
                    substitute_types(item, rewrite)
