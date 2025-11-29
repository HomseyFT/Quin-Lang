from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple
from . import ast as A
from .bytecode import OpCode, Instruction, Bytecode
from .sema import Context
from .types import Int, Str, Bool


@dataclass
class FunctionLayout:
    name: str
    num_locals: int
    local_index: Dict[str, int]
    entry_pc: int
    arrays: Dict[str, int]   # name -> length (for int[N] arrays)


class CodeGenVM:
    def __init__(self):
        self.code: Bytecode = []
        self.functions: List[FunctionLayout] = []
        self.strings: Dict[int, str] = {}
        self._string_counter = 0

    def _add_string(self, value: str) -> int:
        sid = self._string_counter
        self._string_counter += 1
        self.strings[sid] = value
        return sid

    def generate(self, program: A.Program, ctx: Context):
        # For now, simple layout: each function gets its own locals from VarDecls
        for fn in program.functions:
            layout = self._build_layout(fn)
            layout.entry_pc = len(self.code)
            self.functions.append(layout)
            self._emit_function(fn, layout, ctx)
        # Convert FunctionLayout to runtime FunctionInfo in driver
        from runtime.vm import FunctionInfo
        fns = [FunctionInfo(fl.name, fl.entry_pc, fl.num_locals) for fl in self.functions]
        return self.code, fns, self.strings

    def _build_layout(self, fn: A.Function) -> FunctionLayout:
        local_index: Dict[str, int] = {}
        arrays: Dict[str, int] = {}
        next_idx = 0

        def visit_stmt(st: A.Stmt):
            nonlocal next_idx
            if isinstance(st, A.VarDecl):
                if st.name not in local_index:
                    # Determine if this is an int[N] array by its type_name string
                    n = None
                    if st.type_name and isinstance(st.type_name, str) and st.type_name.startswith("int[") and st.type_name.endswith("]"):
                        inner = st.type_name[4:-1]
                        try:
                            n = int(inner)
                        except ValueError:
                            n = None
                    if n is not None and n > 0:
                        # Flatten array into n consecutive locals
                        base = next_idx
                        local_index[st.name] = base
                        arrays[st.name] = n
                        next_idx += n
                    else:
                        local_index[st.name] = next_idx
                        next_idx += 1
            elif isinstance(st, A.If):
                for s in st.then_block:
                    visit_stmt(s)
                if st.else_block:
                    for s in st.else_block:
                        visit_stmt(s)
            elif isinstance(st, A.While):
                for s in st.body:
                    visit_stmt(s)

        for st in fn.body:
            visit_stmt(st)

        return FunctionLayout(fn.name, next_idx, local_index, entry_pc=0, arrays=arrays)

    def _emit_function(self, fn: A.Function, layout: FunctionLayout, ctx: Context):
        for st in fn.body:
            self._emit_stmt(st, layout, ctx)
        # implicit return 0 for main / void
        if fn.return_type is None or fn.return_type == "int":
            # main expects int; others may ignore
            self.code.append(Instruction(OpCode.PUSH_INT, 0))
        self.code.append(Instruction(OpCode.RET))

    def _emit_stmt(self, st: A.Stmt, layout: FunctionLayout, ctx: Context):
        if isinstance(st, A.VarDecl):
            # Initialize scalar or array locals
            idx = layout.local_index[st.name]
            if st.name in layout.arrays:
                length = layout.arrays[st.name]
                # For now, ignore any initializer for arrays and zero all elements
                for offset in range(length):
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
                    self.code.append(Instruction(OpCode.STORE_LOCAL, idx + offset))
            else:
                if st.init is not None:
                    self._emit_expr(st.init, layout, ctx)
                else:
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
                self.code.append(Instruction(OpCode.STORE_LOCAL, idx))
        elif isinstance(st, A.Assign):
            if isinstance(st.target, A.Identifier):
                idx = layout.local_index.get(st.target.name)
                if idx is not None:
                    self._emit_expr(st.value, layout, ctx)
                    self.code.append(Instruction(OpCode.STORE_LOCAL, idx))
            elif isinstance(st.target, A.Index) and isinstance(st.target.array, A.Identifier):
                arr_name = st.target.array.name
                if arr_name in layout.arrays:
                    base = layout.local_index[arr_name]
                    # Evaluate value then index, then store into base+index
                    self._emit_expr(st.value, layout, ctx)    # push value
                    self._emit_expr(st.target.index, layout, ctx)  # push index
                    self.code.append(Instruction(OpCode.STORE_LOCAL_IDX, base))
        elif isinstance(st, A.Print):
            self._emit_expr(st.value, layout, ctx)
            t = ctx.get_type(st.value)
            if t == Str:
                self.code.append(Instruction(OpCode.PRINT_STR))
            else:
                self.code.append(Instruction(OpCode.PRINT_INT))
        elif isinstance(st, A.PrintLn):
            self._emit_expr(st.value, layout, ctx)
            t = ctx.get_type(st.value)
            if t == Str:
                self.code.append(Instruction(OpCode.PRINTLN_STR))
            else:
                self.code.append(Instruction(OpCode.PRINTLN_INT))
        elif isinstance(st, A.Return):
            if st.value is not None:
                self._emit_expr(st.value, layout, ctx)
            else:
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
            self.code.append(Instruction(OpCode.RET))
        elif isinstance(st, A.ExprStmt):
            self._emit_expr(st.expr, layout, ctx)
            # discard result
            # (VM just leaves it on stack; could add a POP if desired)
        elif isinstance(st, A.If):
            self._emit_if(st, layout, ctx)
        elif isinstance(st, A.While):
            self._emit_while(st, layout, ctx)

    def _emit_if(self, st: A.If, layout: FunctionLayout, ctx: Context):
        # cond
        self._emit_expr(st.cond, layout, ctx)
        # placeholder for JZ
        jz_index = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))  # arg to be patched
        # then block
        for s in st.then_block:
            self._emit_stmt(s, layout, ctx)
        # jump over else
        jmp_index = len(self.code)
        self.code.append(Instruction(OpCode.JMP, 0))
        # patch JZ to else start
        else_start = len(self.code)
        self.code[jz_index].arg = else_start
        if st.else_block:
            for s in st.else_block:
                self._emit_stmt(s, layout, ctx)
        end = len(self.code)
        self.code[jmp_index].arg = end

    def _emit_while(self, st: A.While, layout: FunctionLayout, ctx: Context):
        loop_start = len(self.code)
        self._emit_expr(st.cond, layout, ctx)
        jz_index = len(self.code)
        self.code.append(Instruction(OpCode.JZ, 0))
        for s in st.body:
            self._emit_stmt(s, layout, ctx)
        # jump back to top
        self.code.append(Instruction(OpCode.JMP, loop_start))
        loop_end = len(self.code)
        self.code[jz_index].arg = loop_end

    def _emit_expr(self, e: A.Expr, layout: FunctionLayout, ctx: Context):
        if isinstance(e, A.Literal):
            if isinstance(e.value, bool):
                self.code.append(Instruction(OpCode.PUSH_INT, 1 if e.value else 0))
            elif isinstance(e.value, int):
                self.code.append(Instruction(OpCode.PUSH_INT, e.value))
            elif isinstance(e.value, str):
                sid = self._add_string(e.value)
                self.code.append(Instruction(OpCode.PUSH_INT, sid))
        elif isinstance(e, A.Identifier):
            idx = layout.local_index.get(e.name)
            if idx is not None:
                self.code.append(Instruction(OpCode.LOAD_LOCAL, idx))
            else:
                # unknown identifier; treat as 0 for now
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
        elif isinstance(e, A.AddressOf):
            # Represent a pointer as a local index into the current frame.
            if isinstance(e.target, A.Identifier):
                idx = layout.local_index.get(e.target.name)
                if idx is not None:
                    self.code.append(Instruction(OpCode.PUSH_INT, idx))
                else:
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
            elif isinstance(e.target, A.Index) and isinstance(e.target.array, A.Identifier):
                arr_name = e.target.array.name
                if arr_name in layout.arrays:
                    base = layout.local_index[arr_name]
                    # pointer = base + index
                    self._emit_expr(e.target.index, layout, ctx)  # push index
                    self.code.append(Instruction(OpCode.PUSH_INT, base))
                    self.code.append(Instruction(OpCode.ADD))
                else:
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
            else:
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
        elif isinstance(e, A.Unary):
            self._emit_expr(e.right, layout, ctx)
            if e.op == '-':
                self.code.append(Instruction(OpCode.NEG))
            elif e.op == '!':
                self.code.append(Instruction(OpCode.NOT))
        elif isinstance(e, A.Binary):
            self._emit_expr(e.left, layout, ctx)
            self._emit_expr(e.right, layout, ctx)
            if e.op == '+':
                self.code.append(Instruction(OpCode.ADD))
            elif e.op == '-':
                self.code.append(Instruction(OpCode.SUB))
            elif e.op == '*':
                self.code.append(Instruction(OpCode.MUL))
            elif e.op == '/':
                self.code.append(Instruction(OpCode.DIV))
            elif e.op == '==':
                self.code.append(Instruction(OpCode.CMP_EQ))
            elif e.op == '!=':
                self.code.append(Instruction(OpCode.CMP_NE))
            elif e.op == '<':
                self.code.append(Instruction(OpCode.CMP_LT))
            elif e.op == '<=':
                self.code.append(Instruction(OpCode.CMP_LE))
            elif e.op == '>':
                self.code.append(Instruction(OpCode.CMP_GT))
            elif e.op == '>=':
                self.code.append(Instruction(OpCode.CMP_GE))
            # logical &&/|| short-circuit could be added here later
        elif isinstance(e, A.Index):
            # For now, support indexing into local int[N] arrays only.
            if isinstance(e.array, A.Identifier) and e.array.name in layout.arrays:
                base = layout.local_index[e.array.name]
                self._emit_expr(e.index, layout, ctx)  # push index
                self.code.append(Instruction(OpCode.LOAD_LOCAL_IDX, base))
            else:
                # Unknown index target; push 0
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
        elif isinstance(e, A.Call):
            # Handle a few builtins directly in the VM backend.
            name = e.callee
            # array_push(xs: int[N], len: int, value: int) -> int (new len)
            if name == "array_push" and len(e.args) == 3:
                arr_expr, len_expr, val_expr = e.args
                if isinstance(arr_expr, A.Identifier) and arr_expr.name in layout.arrays:
                    base = layout.local_index[arr_expr.name]
                    # xs[len] = value
                    # Evaluate value then index, then store
                    self._emit_expr(val_expr, layout, ctx)      # push value
                    self._emit_expr(len_expr, layout, ctx)      # push len
                    self.code.append(Instruction(OpCode.STORE_LOCAL_IDX, base))
                    # Result: len + 1
                    self._emit_expr(len_expr, layout, ctx)      # push len again
                    self.code.append(Instruction(OpCode.PUSH_INT, 1))
                    self.code.append(Instruction(OpCode.ADD))
                else:
                    # Fallback: just return len + 1 evaluated as int
                    self._emit_expr(len_expr, layout, ctx)
                    self.code.append(Instruction(OpCode.PUSH_INT, 1))
                    self.code.append(Instruction(OpCode.ADD))
            # array_pop(xs: int[N], len: int) -> int (popped value)
            elif name == "array_pop" and len(e.args) == 2:
                arr_expr, len_expr = e.args
                if isinstance(arr_expr, A.Identifier) and arr_expr.name in layout.arrays:
                    base = layout.local_index[arr_expr.name]
                    # Compute len-1 on stack and load that element
                    self._emit_expr(len_expr, layout, ctx)      # push len
                    self.code.append(Instruction(OpCode.PUSH_INT, 1))
                    self.code.append(Instruction(OpCode.SUB))   # len - 1
                    self.code.append(Instruction(OpCode.LOAD_LOCAL_IDX, base))
                else:
                    # Fallback: just return 0
                    self.code.append(Instruction(OpCode.PUSH_INT, 0))
            # Pointer/memory intrinsics using local-index pointers
            elif name == "load16" and len(e.args) == 1:
                # p: ptr -> local index
                self._emit_expr(e.args[0], layout, ctx)   # push ptr
                self.code.append(Instruction(OpCode.LOAD_INDIRECT))
            elif name == "store16" and len(e.args) == 2:
                # store16(p, value): writes to local indexed by p
                self._emit_expr(e.args[0], layout, ctx)   # push ptr
                self._emit_expr(e.args[1], layout, ctx)   # push value
                # Stack order for STORE_INDIRECT: [..., ptr, value]
                # We currently have [..., ptr, value]; rearrange to [..., value, ptr]
                # by using a small pattern: push ptr again, LOAD_INDIRECT not needed; for now, swap via temp
                # Simpler: emit STORE_INDIRECT expecting [ptr, value], then adjust VM.
                # But VM currently expects [p, v] in that order.
                # So we change VM: STORE_INDIRECT pops v then p; here we want [..., ptr, value].
                # That is already correct; nothing extra needed.
                self.code.append(Instruction(OpCode.STORE_INDIRECT))
                # store16 returns void; push 0 as dummy value so expressions have a result
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
            elif name == "memcpy" and len(e.args) == 3:
                # memcpy(dst, src, count): operate on locals as elements
                self._emit_expr(e.args[0], layout, ctx)  # dst ptr
                self._emit_expr(e.args[1], layout, ctx)  # src ptr
                self._emit_expr(e.args[2], layout, ctx)  # count (elements)
                self.code.append(Instruction(OpCode.MEMCPY_LOCALS))
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
            elif name == "memset" and len(e.args) == 3:
                # memset(dst, value, count): operate on locals as elements
                self._emit_expr(e.args[0], layout, ctx)  # dst ptr
                self._emit_expr(e.args[1], layout, ctx)  # value
                self._emit_expr(e.args[2], layout, ctx)  # count (elements)
                self.code.append(Instruction(OpCode.MEMSET_LOCALS))
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
            else:
                # For now, treat other calls as returning 0 in VM subset
                self.code.append(Instruction(OpCode.PUSH_INT, 0))
