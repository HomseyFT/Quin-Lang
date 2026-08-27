"""The opcode numbering, pinned.

An opcode's number is not an implementation detail: it is what a serialised
program is made of, and what an old file means when a new compiler reads it.
These tests exist so that changing one is a deliberate act with a failing test
attached, rather than a side effect of tidying the enum.

Adding an opcode does not require touching this file. Renumbering, reordering,
or reusing a retired number does.
"""

import unittest

from compiler.bytecode import OpCode

# Every opcode that has ever shipped, with the number it shipped as. Add a line
# when you add an opcode; never change one that is already here.
FROZEN = {
    "PUSH_INT": 1,
    "LOAD_LOCAL": 2,
    "STORE_LOCAL": 3,
    "ADD": 4,
    "SUB": 5,
    "MUL": 6,
    "DIV": 7,
    "MOD": 8,
    "XOR": 9,
    "AND": 10,
    "OR": 11,
    "SHL": 12,
    "SHR": 13,
    "NEG": 14,
    "CMP_EQ": 15,
    "CMP_NE": 16,
    "CMP_LT": 17,
    "CMP_LE": 18,
    "CMP_GT": 19,
    "CMP_GE": 20,
    "LOAD_STR": 21,
    "STR_CMP": 22,
    "STR_LEN": 23,
    "STR_CHAR_AT": 24,
    "STR_CONCAT": 25,
    "STR_SLICE": 26,
    "STR_FROM_INT": 27,
    "STR_FROM_CHAR": 28,
    "PUSH_FLOAT": 29,
    "LOAD_LOCAL_F": 30,
    "STORE_LOCAL_F": 31,
    "FADD": 32,
    "FSUB": 33,
    "FMUL": 34,
    "FDIV": 35,
    "FNEG": 36,
    "FCMP": 37,
    "F_FROM_INT": 38,
    "F_TO_INT": 39,
    "STR_FROM_FLOAT": 40,
    "PRINT_FLOAT": 41,
    "PRINTLN_FLOAT": 42,
    "NOT": 43,
    "BITNOT": 44,
    "JMP": 45,
    "JZ": 46,
    "JNZ": 47,
    "CALL": 48,
    "RET": 49,
    "LOAD_LOCAL_IDX": 50,
    "STORE_LOCAL_IDX": 51,
    "BOUNDS_CHECK": 52,
    "LOAD_INDIRECT": 53,
    "STORE_INDIRECT": 54,
    "MEMCPY_LOCALS": 55,
    "MEMSET_LOCALS": 56,
    "POP": 57,
    "DUP": 58,
    "SWAP": 59,
    "PRINT_INT": 60,
    "PRINT_STR": 61,
    "PRINTLN_INT": 62,
    "PRINTLN_STR": 63,
    "ALLOC": 64,
    "ALLOC_TYPED": 65,
    "HEAP_LOAD": 66,
    "HEAP_STORE": 67,
    "HEAP_LOAD_FIELD": 68,
    "HEAP_STORE_FIELD": 69,
    "HEAP_LOAD_FIELD_F": 70,
    "HEAP_STORE_FIELD_F": 71,
    "GC": 72,
    "PANIC": 73,
}

# Numbers of opcodes that once existed and were removed. A retired number is
# never reused: an old file that names it should fail to load, not decode into
# whatever took its place.
RETIRED: set = set()


class TestOpcodeNumbering(unittest.TestCase):
    def test_every_frozen_opcode_keeps_its_number(self):
        current = {op.name: op.value for op in OpCode}
        drifted = {
            name: (number, current.get(name))
            for name, number in FROZEN.items()
            if current.get(name) != number
        }
        self.assertEqual(
            drifted, {},
            "an opcode changed number or was removed. Every .qlc file ever "
            "written names opcodes by number, so this silently changes what "
            "they mean. Removing one? Leave the number out and add it to "
            "RETIRED instead of renumbering the rest.",
        )

    def test_a_new_opcode_is_recorded(self):
        # The other direction: adding one is fine, but it has to be written
        # down here, which is the moment to notice the format grew.
        unrecorded = sorted(op.name for op in OpCode if op.name not in FROZEN)
        self.assertEqual(unrecorded, [],
                         "add these to FROZEN with the number they now have")

    def test_numbers_are_unique(self):
        seen = {}
        for op in OpCode:
            self.assertNotIn(op.value, seen,
                             f"{op.name} collides with {seen.get(op.value)}")
            seen[op.value] = op.name

    def test_zero_is_not_an_opcode(self):
        # Left free so a format can use it as a terminator or an "absent" mark.
        self.assertNotIn(0, [op.value for op in OpCode])

    def test_no_retired_number_is_reused(self):
        reused = sorted(op.name for op in OpCode if op.value in RETIRED)
        self.assertEqual(reused, [],
                         "these took the number of a removed opcode")

    def test_the_set_still_fits_one_byte(self):
        # Not a hard requirement, but a one-byte opcode field is the obvious
        # encoding and this says when that stops being possible.
        self.assertLessEqual(max(op.value for op in OpCode), 255,
                             "the instruction set outgrew a byte")


class TestEnumShape(unittest.TestCase):
    def test_every_member_is_assigned_a_literal_number(self):
        # auto() numbers by position, so an insert renumbers everything after
        # it. Checked against the assignment lines rather than the whole class
        # source, which discusses auto() in its docstring.
        import inspect
        import re
        from compiler import bytecode

        assignments = re.findall(
            r"^\s+([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*(?:#.*)?$",
            inspect.getsource(bytecode.OpCode),
            re.MULTILINE,
        )
        self.assertEqual(len(assignments), len(list(OpCode)),
                         "every member should have been found")
        not_literal = [name for name, value in assignments if not value.isdigit()]
        self.assertEqual(not_literal, [],
                         "these are computed rather than written down")


if __name__ == "__main__":
    unittest.main()
