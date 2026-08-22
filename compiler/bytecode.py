from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple, Union


class OpCode(Enum):
    # Stack and locals
    PUSH_INT = auto()
    LOAD_LOCAL = auto()
    STORE_LOCAL = auto()

    # Arithmetic
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    XOR = auto()
    AND = auto()
    OR = auto()
    SHL = auto()
    SHR = auto()
    NEG = auto()

    # Comparisons (push 0/1)
    CMP_EQ = auto()
    CMP_NE = auto()
    CMP_LT = auto()
    CMP_LE = auto()
    CMP_GT = auto()
    CMP_GE = auto()

    # Strings. A str value is the heap address of a string object, so these
    # read and build objects rather than indexing a host-side table.
    LOAD_STR = auto()      # operand: literal id
    STR_CMP = auto()       # push -1, 0 or 1 by content order
    STR_LEN = auto()
    STR_CHAR_AT = auto()   # pop index, then string
    STR_CONCAT = auto()
    STR_SLICE = auto()     # pop end, then start, then string
    STR_FROM_INT = auto()  # decimal text
    STR_FROM_CHAR = auto()

    # Floats. A float is 32 bits: two consecutive slots in a frame or a heap
    # object, but a single operand-stack entry holding the IEEE 754 bit
    # pattern. Splitting it only at the storage boundary keeps every stack
    # opcode -- POP, DUP, SWAP, RET's balance check -- one entry per value.
    PUSH_FLOAT = auto()        # operand: 32-bit bit pattern
    LOAD_LOCAL_F = auto()      # operand: base slot; reads two words
    STORE_LOCAL_F = auto()     # operand: base slot; writes two words
    FADD = auto()
    FSUB = auto()
    FMUL = auto()
    FDIV = auto()
    FNEG = auto()
    # Like STR_CMP: reduce the pair to -1/0/1 so the six integer comparison
    # opcodes can test it against zero, rather than duplicating all six.
    FCMP = auto()
    F_FROM_INT = auto()
    F_TO_INT = auto()          # truncates toward zero, like integer division
    STR_FROM_FLOAT = auto()
    PRINT_FLOAT = auto()
    PRINTLN_FLOAT = auto()

    # Logical
    NOT = auto()
    BITNOT = auto()

    # Control flow
    JMP = auto()           # operand: target pc
    JZ = auto()            # operand: target pc; pops the value it tests
    JNZ = auto()           # operand: target pc; pops the value it tests

    # Function calls
    CALL = auto()          # operand: function index
    RET = auto()

    # Arrays as locals: base index is encoded in operand
    LOAD_LOCAL_IDX = auto()
    STORE_LOCAL_IDX = auto()
    BOUNDS_CHECK = auto()      # operand: element count; inspects the index without popping it

    # Indirect access using "pointer" as local index
    LOAD_INDIRECT = auto()     # pop p; push locals[p]
    STORE_INDIRECT = auto()    # pop v, pop p; locals[p] = v
    MEMCPY_LOCALS = auto()     # pop count, src, dst
    MEMSET_LOCALS = auto()     # pop count, value, dst

    # Stack management
    POP = auto()
    DUP = auto()
    SWAP = auto()

    # Builtin-style I/O
    PRINT_INT = auto()
    PRINT_STR = auto()
    PRINTLN_INT = auto()
    PRINTLN_STR = auto()

    # Heap operations
    ALLOC = auto()             # pop size in bytes
    ALLOC_TYPED = auto()       # operand: struct type id
    HEAP_LOAD = auto()
    HEAP_STORE = auto()
    # The field offset is an operand rather than an ADD on the address, so the
    # null check tests the object reference itself: adding first would turn a
    # null base into a small non-zero address and read whatever is there.
    HEAP_LOAD_FIELD = auto()   # operand: word offset; pop ref
    HEAP_STORE_FIELD = auto()  # operand: word offset; pop value, pop ref
    HEAP_LOAD_FIELD_F = auto()   # operand: word offset; pop ref, push the float in two words there
    HEAP_STORE_FIELD_F = auto()  # operand: word offset; pop float, pop ref
    GC = auto()
    PANIC = auto()             # pop a message id and stop the program


Operand = Union[int, None]


@dataclass(frozen=True)
class SourceMap:
    """Which source position each instruction came from.

    Stored beside the bytecode rather than on Instruction so the interpreter
    loop and the instruction itself stay the size they were: nothing reads this
    until something goes wrong, or a debugger asks.

    It is a list of markers, not one entry per instruction. A marker says "from
    this pc onward, the position is this", which is how a run of instructions
    lowered from one expression costs a single entry. `pcs` is sorted, so a
    lookup is a binary search.
    """
    pcs: Tuple[int, ...] = ()
    positions: Tuple[Tuple[int, int], ...] = ()

    def lookup(self, pc: int) -> Optional[Tuple[int, int]]:
        """The (line, col) in force at `pc`, or None if it is before the first
        marker -- which happens only for code no statement produced."""
        i = bisect_right(self.pcs, pc) - 1
        if i < 0:
            return None
        return self.positions[i]

    def describe(self, pc: int) -> str:
        """`[line:col]` for `pc`, or an empty string when it is unmapped, so a
        caller can concatenate without checking."""
        pos = self.lookup(pc)
        return f"[{pos[0]}:{pos[1]}]" if pos else ""


class SourceMapBuilder:
    """Accumulates markers while codegen walks the AST.

    Codegen notes the node it is lowering on the way in and restores the
    enclosing node's position on the way out, so the position in force is
    always the innermost node that produced the instruction.
    """

    def __init__(self):
        self._pcs: List[int] = []
        self._positions: List[Tuple[int, int]] = []

    def mark(self, pc: int, line: int, col: int) -> None:
        pos = (line, col)
        if self._pcs and self._pcs[-1] == pc:
            # Nothing was emitted since the last marker, so that marker
            # described no instruction. The innermost node wins.
            self._positions[-1] = pos
            return
        if self._positions and self._positions[-1] == pos:
            return
        self._pcs.append(pc)
        self._positions.append(pos)

    def build(self) -> SourceMap:
        return SourceMap(tuple(self._pcs), tuple(self._positions))


@dataclass
class Instruction:
    op: OpCode
    arg: Operand = None


Bytecode = List[Instruction]
