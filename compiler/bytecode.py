from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Union


class OpCode(Enum):
    """The instruction set. Values are written out, never auto().

    An opcode's number is what a serialised program is made of, so it is part
    of the format and not an implementation detail. auto() numbers by position,
    which means inserting an opcode anywhere but the end silently renumbers
    every one after it -- and a file written before that insert would still
    load, as a different program. Explicit values make an insert additive, and
    tests/test_opcodes.py pins every one so a reordering fails rather than
    quietly changing what old bytecode means.

    Add new opcodes at the end with the next free number. Never reuse the
    number of one you remove: leave the hole, so an old file fails to load
    instead of decoding into something else. 0 is reserved as "not an opcode".
    """

    # Stack and locals
    PUSH_INT = 1
    LOAD_LOCAL = 2
    STORE_LOCAL = 3

    # Arithmetic
    ADD = 4
    SUB = 5
    MUL = 6
    DIV = 7
    MOD = 8
    XOR = 9
    AND = 10
    OR = 11
    SHL = 12
    SHR = 13
    NEG = 14

    # Comparisons (push 0/1)
    CMP_EQ = 15
    CMP_NE = 16
    CMP_LT = 17
    CMP_LE = 18
    CMP_GT = 19
    CMP_GE = 20

    # Strings. A str value is the heap address of a string object, so these
    # read and build objects rather than indexing a host-side table.
    LOAD_STR = 21      # operand: literal id
    STR_CMP = 22       # push -1, 0 or 1 by content order
    STR_LEN = 23
    STR_CHAR_AT = 24   # pop index, then string
    STR_CONCAT = 25
    STR_SLICE = 26     # pop end, then start, then string
    STR_FROM_INT = 27  # decimal text
    STR_FROM_CHAR = 28

    # Floats. A float is 32 bits: two consecutive slots in a frame or a heap
    # object, but a single operand-stack entry holding the IEEE 754 bit
    # pattern. Splitting it only at the storage boundary keeps every stack
    # opcode -- POP, DUP, SWAP, RET's balance check -- one entry per value.
    PUSH_FLOAT = 29        # operand: 32-bit bit pattern
    LOAD_LOCAL_F = 30      # operand: base slot; reads two words
    STORE_LOCAL_F = 31     # operand: base slot; writes two words
    FADD = 32
    FSUB = 33
    FMUL = 34
    FDIV = 35
    FNEG = 36
    # Like STR_CMP: reduce the pair to -1/0/1 so the six integer comparison
    # opcodes can test it against zero, rather than duplicating all six.
    FCMP = 37
    F_FROM_INT = 38
    F_TO_INT = 39          # truncates toward zero, like integer division
    STR_FROM_FLOAT = 40
    PRINT_FLOAT = 41
    PRINTLN_FLOAT = 42

    # Logical
    NOT = 43
    BITNOT = 44

    # Control flow
    JMP = 45           # operand: target pc
    JZ = 46            # operand: target pc; pops the value it tests
    JNZ = 47           # operand: target pc; pops the value it tests

    # Function calls
    CALL = 48          # operand: function index
    RET = 49

    # Arrays as locals: base index is encoded in operand
    LOAD_LOCAL_IDX = 50
    STORE_LOCAL_IDX = 51
    BOUNDS_CHECK = 52      # operand: element count; inspects the index without popping it

    # Indirect access using "pointer" as local index
    LOAD_INDIRECT = 53     # pop p; push locals[p]
    STORE_INDIRECT = 54    # pop v, pop p; locals[p] = v
    MEMCPY_LOCALS = 55     # pop count, src, dst
    MEMSET_LOCALS = 56     # pop count, value, dst

    # Stack management
    POP = 57
    DUP = 58
    SWAP = 59

    # Builtin-style I/O
    PRINT_INT = 60
    PRINT_STR = 61
    PRINTLN_INT = 62
    PRINTLN_STR = 63

    # Heap operations
    ALLOC = 64             # pop size in bytes
    ALLOC_TYPED = 65       # operand: struct type id
    HEAP_LOAD = 66
    HEAP_STORE = 67
    # The field offset is an operand rather than an ADD on the address, so the
    # null check tests the object reference itself: adding first would turn a
    # null base into a small non-zero address and read whatever is there.
    HEAP_LOAD_FIELD = 68   # operand: word offset; pop ref
    HEAP_STORE_FIELD = 69  # operand: word offset; pop value, pop ref
    HEAP_LOAD_FIELD_F = 70   # operand: word offset; pop ref, push the float in two words there
    HEAP_STORE_FIELD_F = 71  # operand: word offset; pop float, pop ref
    GC = 72
    PANIC = 73             # pop a message id and stop the program


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

    # Setting a breakpoint runs the map the other way: from a line the user
    # named to the pc to stop at. Both searches take a pc range because a line
    # number alone is ambiguous -- the map covers every function in the program,
    # and line 30 exists in std/math.ql as surely as in the user's file. The
    # caller narrows to one function, whose file it knows.

    def lines_in(self, start: int = 0, end: Optional[int] = None) -> Tuple[int, ...]:
        """The source lines carrying code in `[start, end)`, ascending.

        What a breakpoint can actually be set on: a blank line or a comment
        produces no instruction and so never appears here.
        """
        return tuple(sorted({
            line for pc, (line, _) in zip(self.pcs, self.positions)
            if pc >= start and (end is None or pc < end)
        }))

    def first_pc_on_line(self, line: int, start: int = 0,
                         end: Optional[int] = None) -> Optional[int]:
        """The lowest pc in `[start, end)` attributed to `line`, or None.

        The lowest rather than any, so a breakpoint fires as the line begins.
        A line reached repeatedly -- a loop body, a condition re-tested each
        iteration -- keeps one pc and so stops on every pass.
        """
        candidates = [
            pc for pc, (l, _) in zip(self.pcs, self.positions)
            if l == line and pc >= start and (end is None or pc < end)
        ]
        return min(candidates) if candidates else None


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
