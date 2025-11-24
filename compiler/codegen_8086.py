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
        if isinstance(e, A.Call):
            # Zero-arg calls only for now
            self.em.emit(f"call {e.callee}")
            return
        self.em.emit("xor ax, ax")
