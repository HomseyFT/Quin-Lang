from typing import Optional
from . import ast as A
from .emitter import Emitter
from .sema import Context
from .layout import LayoutBuilder
from .types import Int, Str, Bool

class CodeGen8086:
    def __init__(self):
        self.em = Emitter()
        self.fn_locals = {}  # name -> offset

    def generate(self, program: A.Program, ctx: Context) -> str:
        for fn in program.functions:
            self._emit_function(fn, ctx)
        return self.em.render()

    def _emit_function(self, fn: A.Function, ctx: Context):
        # Prologue
        lb = LayoutBuilder()
        layout = lb.build_for_function(fn)
        self.fn_locals = layout.offsets
        self.em.emit(f"global {fn.name}")
        self.em.label(fn.name)
        self.em.emit("push bp")
        self.em.emit("mov bp, sp")
        if layout.size > 0:
            self.em.emit(f"sub sp, {layout.size}")
        # Body
        for st in fn.body:
            self._emit_stmt(st, ctx)
        # Epilogue (implicit return)
        self._emit_epilogue()

    def _emit_epilogue(self):
        self.em.emit("mov sp, bp")
        self.em.emit("pop bp")
        self.em.emit("ret")

    def _emit_stmt(self, st: A.Stmt, ctx: Context):
        if isinstance(st, A.Print):
            self._emit_expr(st.value, ctx)
            t = ctx.get_type(st.value)
            if t == Str:
                # AX holds pointer to '$' string
                self.em.emit("mov dx, ax")
                self.em.emit("call rt_print_str")
            else:
                self.em.emit("call rt_print_num16")
        elif isinstance(st, A.Return):
            if st.value:
                self._emit_expr(st.value, ctx)
            self._emit_epilogue()
        elif isinstance(st, A.ExprStmt):
            self._emit_expr(st.expr, ctx)
        elif isinstance(st, A.VarDecl):
            # initialize or zero
            if st.init:
                self._emit_expr(st.init, ctx)
            else:
                self.em.emit("xor ax, ax")
            if st.name in self.fn_locals:
                off = self.fn_locals[st.name]
                self.em.emit(f"mov [bp-{off}], ax")
        elif isinstance(st, A.Assign):
            # Handle identifier assignment only for now; array element assignment
            # will be handled via Index in a later pass.
            if isinstance(st.target, A.Identifier):
                self._emit_expr(st.value, ctx)
                off = self.fn_locals.get(st.target.name)
                if off is not None:
                    self.em.emit(f"mov [bp-{off}], ax")
        elif isinstance(st, A.If):
            else_lbl = self.em.unique_label("ELSE")
            end_lbl = self.em.unique_label("ENDIF")
            self._emit_expr(st.cond, ctx)
            self.em.emit("cmp ax, 0")
            self.em.emit(f"je {else_lbl}")
            for s in st.then_block:
                self._emit_stmt(s, ctx)
            self.em.emit(f"jmp {end_lbl}")
            self.em.label(else_lbl)
            if st.else_block:
                for s in st.else_block:
                    self._emit_stmt(s, ctx)
            self.em.label(end_lbl)
        elif isinstance(st, A.While):
            top = self.em.unique_label("WHL")
            end = self.em.unique_label("ENDW")
            self.em.label(top)
            self._emit_expr(st.cond, ctx)
            self.em.emit("cmp ax, 0")
            self.em.emit(f"je {end}")
            for s in st.body:
                self._emit_stmt(s, ctx)
            self.em.emit(f"jmp {top}")
            self.em.label(end)

    def _emit_expr(self, e: A.Expr, ctx: Context):
        if isinstance(e, A.Literal):
            if isinstance(e.value, int):
                self.em.emit(f"mov ax, {e.value}")
                return
            if isinstance(e.value, str):
                lbl = self.em.add_string(e.value)
                self.em.emit(f"mov ax, {lbl}")
                return
            if isinstance(e.value, bool):
                self.em.emit(f"mov ax, {1 if e.value else 0}")
                return
        if isinstance(e, A.Identifier):
            off = self.fn_locals.get(e.name)
            if off is not None:
                self.em.emit(f"mov ax, [bp-{off}]")
            else:
                self.em.emit("xor ax, ax")
            return
        if isinstance(e, A.AddressOf):
            # Compute pointer value (offset within SS) for locals/array elements.
            if isinstance(e.target, A.Identifier):
                off = self.fn_locals.get(e.target.name)
                if off is not None:
                    # Address of scalar/array base: bp-off
                    self.em.emit(f"lea ax, [bp-{off}]")
                else:
                    self.em.emit("xor ax, ax")
                return
            if isinstance(e.target, A.Index) and isinstance(e.target.array, A.Identifier):
                arr_name = e.target.array.name
                if arr_name in self.fn_locals:
                    off = self.fn_locals[arr_name]
                    # Compute index into SI (index * 2)
                    self._emit_expr(e.target.index, ctx)  # AX = index
                    self.em.emit("mov si, ax")
                    self.em.emit("shl si, 1")           # 2-byte elements
                    # Effective address = bp+si-off
                    self.em.emit(f"lea ax, [bp+si-{off}]")
                    return
            # Fallback: null pointer
            self.em.emit("xor ax, ax")
            return
        if isinstance(e, A.Unary):
            self._emit_expr(e.right, ctx)
            if e.op == '-':
                self.em.emit("neg ax")
            elif e.op == '!':
                self.em.emit("cmp ax, 0")
                t_lbl = self.em.unique_label("T")
                e_lbl = self.em.unique_label("E")
                self.em.emit(f"je {t_lbl}")
                self.em.emit("xor ax, ax")
                self.em.emit(f"jmp {e_lbl}")
                self.em.label(t_lbl)
                self.em.emit("mov ax, 1")
                self.em.label(e_lbl)
            return
        if isinstance(e, A.Binary):
            lt = ctx.get_type(e.left)
            rt = ctx.get_type(e.right)
            if lt == Str and rt == Str and e.op in ('==', '!=', '<', '<=', '>', '>='):
                # string compare
                self._emit_expr(e.left, ctx)   # AX = left
                self.em.emit("push ax")
                self._emit_expr(e.right, ctx)  # AX = right
                self.em.emit("mov di, ax")
                self.em.emit("pop si")
                self.em.emit("call rt_str_cmp")  # AX <0, =0, >0
                t = self.em.unique_label("T")
                e_lbl = self.em.unique_label("E")
                if e.op == '==':
                    self.em.emit("cmp ax, 0")
                    self.em.emit(f"je {t}")
                elif e.op == '!=':
                    self.em.emit("cmp ax, 0")
                    self.em.emit(f"jne {t}")
                elif e.op == '<':
                    self.em.emit("cmp ax, 0")
                    self.em.emit(f"jl {t}")
                elif e.op == '<=':
                    self.em.emit("cmp ax, 0")
                    self.em.emit(f"jle {t}")
                elif e.op == '>':
                    self.em.emit("cmp ax, 0")
                    self.em.emit(f"jg {t}")
                elif e.op == '>=':
                    self.em.emit("cmp ax, 0")
                    self.em.emit(f"jge {t}")
                self.em.emit("xor ax, ax")
                self.em.emit(f"jmp {e_lbl}")
                self.em.label(t)
                self.em.emit("mov ax, 1")
                self.em.label(e_lbl)
                return
            # integer ops
            self._emit_expr(e.left, ctx)
            self.em.emit("push ax")
            self._emit_expr(e.right, ctx)
            self.em.emit("pop bx")
            if e.op == '+':
                self.em.emit("add ax, bx")
            elif e.op == '-':
                self.em.emit("sub bx, ax")
                self.em.emit("mov ax, bx")
            elif e.op == '*':
                self.em.emit("imul bx")
            elif e.op == '/':
                self.em.emit("cwd")
                self.em.emit("idiv bx")
            elif e.op in ('==', '!=', '<', '<=', '>', '>='):
                self.em.emit("cmp bx, ax")
                t = self.em.unique_label("T")
                e_lbl = self.em.unique_label("E")
                if e.op == '==':
                    self.em.emit(f"je {t}")
                elif e.op == '!=':
                    self.em.emit(f"jne {t}")
                elif e.op == '<':
                    self.em.emit(f"jl {t}")
                elif e.op == '<=':
                    self.em.emit(f"jle {t}")
                elif e.op == '>':
                    self.em.emit(f"jg {t}")
                elif e.op == '>=':
                    self.em.emit(f"jge {t}")
                self.em.emit("xor ax, ax")
                self.em.emit(f"jmp {e_lbl}")
                self.em.label(t)
                self.em.emit("mov ax, 1")
                self.em.label(e_lbl)
            return
        if isinstance(e, A.Index):
            # Currently support indexing into local int[N] arrays only.
            # e.array must be an Identifier naming a local.
            if isinstance(e.array, A.Identifier) and e.array.name in self.fn_locals:
                off = self.fn_locals[e.array.name]
                # Compute index into SI (index * 2)
                self._emit_expr(e.index, ctx)   # AX = index
                self.em.emit("mov si, ax")
                self.em.emit("shl si, 1")      # 2-byte elements
                # Access via SS:BP using BP+SI-displacement addressing.
                # Base local address is [bp-off]; element i is [bp+si-off].
                self.em.emit(f"mov ax, [bp+si-{off}]")
                return
            # Fallback: unknown location, just zero AX
            self.em.emit("xor ax, ax")
            return
        if isinstance(e, A.Call):
            # Lower certain builtins inline; fall back to normal calls otherwise.
            name = e.callee
            # load16(p: ptr) -> int
            if name == "load16" and len(e.args) == 1:
                self._emit_expr(e.args[0], ctx)  # AX = p
                self.em.emit("mov bx, ax")
                self.em.emit("mov ax, [bx]")
                return
            # store16(p: ptr, value: int) -> void
            if name == "store16" and len(e.args) == 2:
                # Evaluate pointer
                self._emit_expr(e.args[0], ctx)
                self.em.emit("mov bx, ax")
                # Evaluate value
                self._emit_expr(e.args[1], ctx)
                self.em.emit("mov [bx], ax")
                # AX is arbitrary for void; leave as value
                return
            # memcpy(dst: ptr, src: ptr, count: int) -> void
            if name == "memcpy" and len(e.args) == 3:
                # dst -> DI
                self._emit_expr(e.args[0], ctx)
                self.em.emit("mov di, ax")
                # src -> SI
                self._emit_expr(e.args[1], ctx)
                self.em.emit("mov si, ax")
                # count -> CX
                self._emit_expr(e.args[2], ctx)
                self.em.emit("mov cx, ax")
                loop_lbl = self.em.unique_label("MEMCPY_LOOP")
                end_lbl = self.em.unique_label("MEMCPY_END")
                self.em.label(loop_lbl)
                self.em.emit("cmp cx, 0")
                self.em.emit(f"je {end_lbl}")
                self.em.emit("mov al, [si]")
                self.em.emit("mov [di], al")
                self.em.emit("inc si")
                self.em.emit("inc di")
                self.em.emit("dec cx")
                self.em.emit(f"jmp {loop_lbl}")
                self.em.label(end_lbl)
                # AX arbitrary
                return
            # memset(dst: ptr, value: int, count: int) -> void
            if name == "memset" and len(e.args) == 3:
                # dst -> DI
                self._emit_expr(e.args[0], ctx)
                self.em.emit("mov di, ax")
                # value -> AL (low byte)
                self._emit_expr(e.args[1], ctx)
                self.em.emit("mov al, al")  # value already in AX; AL used below
                # count -> CX
                self._emit_expr(e.args[2], ctx)
                self.em.emit("mov cx, ax")
                loop_lbl = self.em.unique_label("MEMSET_LOOP")
                end_lbl = self.em.unique_label("MEMSET_END")
                self.em.label(loop_lbl)
                self.em.emit("cmp cx, 0")
                self.em.emit(f"je {end_lbl}")
                self.em.emit("mov [di], al")
                self.em.emit("inc di")
                self.em.emit("dec cx")
                self.em.emit(f"jmp {loop_lbl}")
                self.em.label(end_lbl)
                return
            # array_push(xs: int[N], len: int, value: int) -> int (new len)
            if name == "array_push" and len(e.args) == 3:
                arr_expr, len_expr, val_expr = e.args
                if isinstance(arr_expr, A.Identifier) and arr_expr.name in self.fn_locals:
                    off = self.fn_locals[arr_expr.name]
                    # Evaluate current length and compute element address.
                    # Keep original length in DX so we can return len+1.
                    self._emit_expr(len_expr, ctx)   # AX = len_old
                    self.em.emit("mov dx, ax")       # DX = len_old
                    self.em.emit("mov si, ax")
                    self.em.emit("shl si, 1")       # index * 2
                    # Evaluate value and store into array slot [bp+si-off]
                    self._emit_expr(val_expr, ctx)   # AX = value
                    self.em.emit(f"mov [bp+si-{off}], ax")
                    # Return len_old + 1 in AX
                    self.em.emit("mov ax, dx")
                    self.em.emit("inc ax")
                    return
            # array_pop(xs: int[N], len: int) -> int (popped value)
            if name == "array_pop" and len(e.args) == 2:
                arr_expr, len_expr = e.args
                if isinstance(arr_expr, A.Identifier) and arr_expr.name in self.fn_locals:
                    off = self.fn_locals[arr_expr.name]
                    # Compute len-1 into AX and use as index
                    self._emit_expr(len_expr, ctx)  # AX = len
                    self.em.emit("dec ax")         # len - 1
                    self.em.emit("mov si, ax")
                    self.em.emit("shl si, 1")      # index * 2
                    # Load from [bp+si-off] using SS:BP addressing
                    self.em.emit(f"mov ax, [bp+si-{off}]")   # return value
                    return
            # Fallback: normal function call (no arguments pushed yet)
            self.em.emit(f"call {name}")
            return
        self.em.emit("xor ax, ax")
