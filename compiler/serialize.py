"""The `.qlc` bytecode file: a compiled program, written down.

A `.qlc` is a **build artifact, not an archive format**. The header stamps a
format version and the loader refuses anything else, the way a `.pyc` refuses a
foreign magic. That is what keeps the tables underneath free to change: promise
that an old file still loads and every one of them -- the opcode numbering, the
struct encoding, the debug tables -- becomes frozen public surface, with a
migration path owed on each bump. Refusing is a one-line message telling the
user to recompile, and loosening it later is easy where tightening it would not
be.

Opcodes are the exception that proves it. Their numbers are written out in
`bytecode.py` rather than left to `auto()` precisely so an insert cannot
silently renumber the rest, and this is the format that made that matter.

**What `--strip` leaves out** is everything only a reader of source cares
about: the source map, the local-name tables, and the file each function came
from. That costs more than the debugger -- a runtime error keeps its message
but loses its `[line:col]` and the line numbers in its backtrace -- so it is
opt-in. Function names stay either way; a backtrace naming no functions is not
worth the bytes saved.

Everything is little-endian, and every string is a byte count followed by
UTF-8. Program string literals hold one byte per character by definition, so
encoding them as UTF-8 widens some of them on disk and returns exactly what
went in.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, List, Tuple

from runtime.vm import FieldLayout, FunctionInfo, LocalInfo, StructLayout

from .bytecode import Instruction, OpCode, SourceMap
from .codegen_vm import CompiledProgram

# "QLC" and a DOS end-of-file, so that dumping one to a terminal stops early
# rather than filling the screen with bytecode.
MAGIC = b"QLC\x1a"

# Bumped whenever the layout below changes in any way. There is no migration
# path by design: a file from another version is refused, not upgraded.
FORMAT_VERSION = 1

# Header flags.
HAS_DEBUG_INFO = 1 << 0

# An instruction's opcode field carries whether an operand follows, so the
# reader never needs a table of which opcodes take one -- a table that could
# fall out of step with codegen without anything noticing.
HAS_OPERAND = 1 << 15
MAX_OPCODE = HAS_OPERAND - 1
MAX_OPERAND = 0xFFFFFFFF


class BytecodeError(Exception):
    """A file that is not loadable: wrong magic, wrong version, truncated, or
    naming an opcode this build does not have."""


# -- writing -----------------------------------------------------------------


class _Writer:
    def __init__(self) -> None:
        self.out = bytearray()

    def u8(self, value: int) -> None:
        self.out += struct.pack("<B", value)

    def u16(self, value: int) -> None:
        self.out += struct.pack("<H", value)

    def u32(self, value: int) -> None:
        self.out += struct.pack("<I", value)

    def text(self, value: str) -> None:
        encoded = value.encode("utf-8")
        self.u32(len(encoded))
        self.out += encoded

    def u32_list(self, values) -> None:
        self.u32(len(values))
        for value in values:
            self.u32(value)


def dumps(program: CompiledProgram, debug: bool = True) -> bytes:
    w = _Writer()
    w.out += MAGIC
    w.u16(FORMAT_VERSION)
    w.u16(HAS_DEBUG_INFO if debug else 0)

    _write_strings(w, program.strings)
    _write_structs(w, program.structs)
    _write_functions(w, program.functions, debug)
    _write_code(w, program.code)
    if debug:
        _write_source_map(w, program.source_map)
    return bytes(w.out)


def _write_strings(w: _Writer, strings: Dict[int, str]) -> None:
    # Ids are written out rather than implied by position: they are literal
    # ids that LOAD_STR names, and nothing here guarantees they are dense.
    w.u32(len(strings))
    for literal_id, text in sorted(strings.items()):
        w.u32(literal_id)
        w.text(text)


def _write_structs(w: _Writer, structs: List[StructLayout]) -> None:
    w.u32(len(structs))
    for layout in structs:
        # The index is the type id an object's header carries, so order is
        # part of the format.
        w.text(layout.name)
        w.u32(layout.word_size)
        w.u8(1 if layout.is_variant else 0)
        w.u32_list(layout.ref_offsets)
        w.u32(len(layout.fields))
        for field in layout.fields:
            w.text(field.name)
            w.text(field.type_name)
            w.u32(field.offset)


def _write_functions(w: _Writer, functions: List[FunctionInfo],
                     debug: bool) -> None:
    w.u32(len(functions))
    for fn in functions:
        w.text(fn.name)
        w.u32(fn.entry_pc)
        w.u32(fn.num_locals)
        w.u32(fn.num_params)
        w.u32_list(fn.ref_slots)
        w.u32_list(fn.param_words)
        if debug:
            w.text(fn.source_file)
            w.u32(len(fn.locals_))
            for local in fn.locals_:
                w.text(local.name)
                w.u32(local.slot)
                w.text(local.type_name)
                w.u32(local.words)
                w.u8(1 if local.is_param else 0)


def _write_code(w: _Writer, code: List[Instruction]) -> None:
    w.u32(len(code))
    for pc, instruction in enumerate(code):
        number = instruction.op.value
        if number > MAX_OPCODE:
            raise BytecodeError(
                f"opcode {instruction.op.name} is numbered {number}, past what "
                f"the format encodes ({MAX_OPCODE})")
        if instruction.arg is None:
            w.u16(number)
            continue
        if not 0 <= instruction.arg <= MAX_OPERAND:
            raise BytecodeError(
                f"{instruction.op.name} at pc {pc} has operand "
                f"{instruction.arg}, outside the 32 bits the format holds")
        w.u16(number | HAS_OPERAND)
        w.u32(instruction.arg)


def _write_source_map(w: _Writer, source_map: SourceMap) -> None:
    w.u32(len(source_map.pcs))
    for pc, (line, col) in zip(source_map.pcs, source_map.positions):
        w.u32(pc)
        w.u32(line)
        w.u32(col)


# -- reading -----------------------------------------------------------------


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise BytecodeError("the file ends in the middle of a record")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def text(self) -> str:
        try:
            return self.take(self.u32()).decode("utf-8")
        except UnicodeDecodeError as e:
            raise BytecodeError(f"a string in the file is not UTF-8: {e}") from e

    def u32_list(self) -> Tuple[int, ...]:
        return tuple(self.u32() for _ in range(self.u32()))


def loads(data: bytes) -> CompiledProgram:
    r = _Reader(data)
    if r.take(len(MAGIC)) != MAGIC:
        raise BytecodeError("not a QuinLang bytecode file")
    version = r.u16()
    if version != FORMAT_VERSION:
        raise BytecodeError(
            f"bytecode format {version}, but this build reads only "
            f"{FORMAT_VERSION}; recompile from source")
    debug = bool(r.u16() & HAS_DEBUG_INFO)

    strings = _read_strings(r)
    structs = _read_structs(r)
    functions = _read_functions(r, debug)
    code = _read_code(r)
    source_map = _read_source_map(r) if debug else SourceMap()

    if r.pos != len(data):
        raise BytecodeError(
            f"{len(data) - r.pos} trailing bytes after the program")
    return CompiledProgram(code=code, functions=functions, strings=strings,
                           structs=structs, source_map=source_map)


# Every field below is read into a local before the record is built. Reading a
# binary format is one long sequence of side effects, and a comprehension or a
# nested call leaves the order to the language rather than saying it.


def _read_strings(r: _Reader) -> Dict[int, str]:
    strings = {}
    for _ in range(r.u32()):
        literal_id = r.u32()
        strings[literal_id] = r.text()
    return strings


def _read_structs(r: _Reader) -> List[StructLayout]:
    layouts = []
    for _ in range(r.u32()):
        name = r.text()
        word_size = r.u32()
        is_variant = bool(r.u8())
        ref_offsets = r.u32_list()
        fields = []
        for _ in range(r.u32()):
            field_name = r.text()
            type_name = r.text()
            fields.append(FieldLayout(field_name, type_name, r.u32()))
        layouts.append(StructLayout(name=name, word_size=word_size,
                                    ref_offsets=ref_offsets,
                                    fields=tuple(fields),
                                    is_variant=is_variant))
    return layouts


def _read_functions(r: _Reader, debug: bool) -> List[FunctionInfo]:
    functions = []
    for _ in range(r.u32()):
        name = r.text()
        entry_pc = r.u32()
        num_locals = r.u32()
        num_params = r.u32()
        fn = FunctionInfo(name=name, entry_pc=entry_pc, num_locals=num_locals,
                          num_params=num_params, ref_slots=r.u32_list(),
                          param_words=r.u32_list())
        if debug:
            fn.source_file = r.text()
            fn.locals_ = _read_locals(r)
        functions.append(fn)
    return functions


def _read_locals(r: _Reader) -> Tuple[LocalInfo, ...]:
    locals_ = []
    for _ in range(r.u32()):
        name = r.text()
        slot = r.u32()
        type_name = r.text()
        words = r.u32()
        locals_.append(LocalInfo(name, slot, type_name, words, bool(r.u8())))
    return tuple(locals_)


def _read_code(r: _Reader) -> List[Instruction]:
    code = []
    for pc in range(r.u32()):
        field = r.u16()
        number = field & MAX_OPCODE
        try:
            op = OpCode(number)
        except ValueError as e:
            raise BytecodeError(
                f"opcode {number} at pc {pc} is not one this build has; the "
                f"file was written by a different compiler") from e
        code.append(Instruction(op, r.u32() if field & HAS_OPERAND else None))
    return code


def _read_source_map(r: _Reader) -> SourceMap:
    pcs, positions = [], []
    for _ in range(r.u32()):
        pcs.append(r.u32())
        line = r.u32()
        positions.append((line, r.u32()))
    return SourceMap(pcs=tuple(pcs), positions=tuple(positions))


# -- files -------------------------------------------------------------------


def write_program(program: CompiledProgram, path: Path,
                  debug: bool = True) -> None:
    Path(path).write_bytes(dumps(program, debug))


def read_program(path: Path) -> CompiledProgram:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise BytecodeError(f"cannot read {path}: {e}") from e
    return loads(data)


def is_bytecode(path: Path) -> bool:
    """Whether `path` holds a `.qlc`, by its first bytes rather than its name.

    What a file *is* is not the caller's to guess from a suffix: a `.qlc`
    renamed to `.ql` would otherwise be handed to the lexer, which would report
    a syntax error on binary data.
    """
    try:
        with open(path, "rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False
