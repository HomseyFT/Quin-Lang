from typing import List, Optional
from .tokens import Token, TokenType
from . import ast as A

class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(message)
        self.line = line
        self.col = col

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.current = 0

    def parse(self) -> A.Program:
        includes: List[A.Include] = []
        while self._match(TokenType.INCLUDE):
            includes.append(self._include())
        funcs: List[A.Function] = []
        structs: List[A.StructDef] = []
        enums: List[A.EnumDef] = []
        while not self._is_at_end():
            if self._check(TokenType.STRUCT):
                structs.append(self._struct_def())
            elif self._check(TokenType.ENUM):
                enums.append(self._enum_def())
            else:
                funcs.append(self._function())
        return A.Program(includes, funcs, structs, enums)

    def _struct_def(self) -> A.StructDef:
        self._consume(TokenType.STRUCT, "Expected 'struct'")
        name_tok = self._consume(TokenType.IDENTIFIER, "Expected struct name")
        self._consume(TokenType.LEFT_BRACE, "Expected '{' after struct name")
        fields: List[A.FieldDef] = []
        while not self._check(TokenType.RIGHT_BRACE):
            f_tok = self._consume(TokenType.IDENTIFIER, "Expected field name")
            self._consume(TokenType.COLON, "Expected ':' after field name")
            f_type = self._type_name()
            fields.append(A.FieldDef(f_tok.lexeme, f_type, line=f_tok.line, col=f_tok.col))
            if not self._match(TokenType.COMMA):
                break
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after struct fields")
        return A.StructDef(name_tok.lexeme, fields, line=name_tok.line, col=name_tok.col)

    def _enum_def(self) -> A.EnumDef:
        """`enum Name { Variant, Variant(type, type), }`

        Payloads are positional, so a variant declares types where a struct
        declares `name: type` pairs. A trailing comma is allowed, as it is in
        a struct.
        """
        self._consume(TokenType.ENUM, "Expected 'enum'")
        name_tok = self._consume(TokenType.IDENTIFIER, "Expected enum name")
        self._consume(TokenType.LEFT_BRACE, "Expected '{' after enum name")
        variants: List[A.VariantDef] = []
        while not self._check(TokenType.RIGHT_BRACE):
            v_tok = self._consume(TokenType.IDENTIFIER, "Expected variant name")
            payload: List[str] = []
            if self._match(TokenType.LEFT_PAREN):
                # `Variant()` is spelled `Variant`: an empty payload list and
                # an absent one would otherwise be two ways to say the same
                # thing, and only one of them can be the interned singleton.
                if self._check(TokenType.RIGHT_PAREN):
                    tok = self._peek()
                    raise ParseError(
                        f"Variant '{v_tok.lexeme}' has an empty payload list; "
                        f"write '{v_tok.lexeme}' without parentheses",
                        tok.line, tok.col,
                    )
                while True:
                    payload.append(self._type_name())
                    if not self._match(TokenType.COMMA):
                        break
                self._consume(TokenType.RIGHT_PAREN, "Expected ')' after variant payload")
            variants.append(A.VariantDef(v_tok.lexeme, payload,
                                         line=v_tok.line, col=v_tok.col))
            if not self._match(TokenType.COMMA):
                break
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after enum variants")
        return A.EnumDef(name_tok.lexeme, variants, line=name_tok.line, col=name_tok.col)

    def _include(self) -> A.Include:
        path_tok = self._consume(TokenType.STRING, "Expected path string after 'include'")
        self._consume(TokenType.SEMICOLON, "Expected ';' after include path")
        return A.Include(path_tok.literal, line=path_tok.line, col=path_tok.col)

    # Helpers
    def _match(self, *types: TokenType) -> bool:
        for t in types:
            if self._check(t):
                self._advance()
                return True
        return False

    def _consume(self, type_: TokenType, msg: str) -> Token:
        if self._check(type_):
            return self._advance()
        tok = self._peek()
        raise ParseError(f"{msg} (found '{tok.lexeme}')", tok.line, tok.col)

    def _check(self, type_: TokenType) -> bool:
        if self._is_at_end():
            return False
        return self._peek().type == type_

    def _advance(self) -> Token:
        if not self._is_at_end():
            self.current += 1
        return self._previous()

    def _is_at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]

    # Grammar
    def _function(self) -> A.Function:
        self._consume(TokenType.FN, "Expected 'fn' at function start")
        name_tok = self._consume(TokenType.IDENTIFIER, "Expected function name")
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after function name")
        params: List[A.Param] = []
        if not self._check(TokenType.RIGHT_PAREN):
            while True:
                p_name_tok = self._consume(TokenType.IDENTIFIER, "Expected parameter name")
                self._consume(TokenType.COLON, "Expected ':' after parameter name")
                p_type = self._type_name()
                params.append(A.Param(p_name_tok.lexeme, p_type, line=p_name_tok.line, col=p_name_tok.col))
                if not self._match(TokenType.COMMA):
                    break
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after parameters")
        ret_type: Optional[str] = None
        if self._match(TokenType.COLON):
            ret_type = self._type_name()
        body = self._block()
        return A.Function(name_tok.lexeme, params, ret_type, body, line=name_tok.line, col=name_tok.col)

    def _type_name(self) -> str:
        if self._match(TokenType.INT):
            base = "int"
        elif self._match(TokenType.STR):
            base = "str"
        elif self._match(TokenType.FLOAT):
            base = "float"
        elif self._match(TokenType.VOID):
            base = "void"
        elif self._match(TokenType.PTR):
            base = "ptr"
        elif self._match(TokenType.HEAPPTR):
            base = "heapptr"
        else:
            tok = self._consume(TokenType.IDENTIFIER, "Expected type name")
            base = tok.lexeme

        if base == "int" and self._match(TokenType.LEFT_BRACKET):
            num_tok = self._consume(TokenType.NUMBER, "Expected array size after '['")
            self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after array size")
            return f"int[{int(num_tok.literal)}]"

        # int is the only array element type. Saying so beats letting the '['
        # fall through to a parse error about an unexpected token.
        if self._check(TokenType.LEFT_BRACKET):
            tok = self._peek()
            raise ParseError(
                f"Only int arrays exist; '{base}[N]' is not a type",
                tok.line, tok.col,
            )

        return base

    def _match_stmt(self, kw_tok) -> A.Match:
        """`match (subject) { Variant(a, b) => { ... } _ => { ... } }`

        The subject is parenthesised, as an `if` or `while` condition is. That
        is not only for consistency: `match r {` is ambiguous, because an
        identifier followed by a brace is how a struct literal begins, so the
        subject would swallow the arms. Arms are not comma-separated, since
        each one already ends in a block.
        """
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'match'")
        subject = self._expression()
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after match subject")
        self._consume(TokenType.LEFT_BRACE, "Expected '{' before match arms")
        arms: List[A.MatchArm] = []
        while not self._check(TokenType.RIGHT_BRACE):
            arms.append(self._match_arm())
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after match arms")
        if not arms:
            raise ParseError("A match needs at least one arm", kw_tok.line, kw_tok.col)
        return A.Match(subject, arms, line=kw_tok.line, col=kw_tok.col)

    def _qualified(self, first) -> str:
        """`Enum::Variant`, given the token for `Enum`.

        Returned as a single dotted-style name rather than a node of its own:
        nothing else in the language nests, so `A::B::C` is a syntax error
        rather than a namespace path.
        """
        self._consume(TokenType.COLON_COLON, "Expected '::'")
        second = self._consume(TokenType.IDENTIFIER, "Expected a variant name after '::'")
        if self._check(TokenType.COLON_COLON):
            tok = self._peek()
            raise ParseError(
                f"'{first.lexeme}::{second.lexeme}::' is not a path; a variant is "
                f"named by its enum and nothing further",
                tok.line, tok.col,
            )
        return f"{first.lexeme}::{second.lexeme}"

    def _match_arm(self) -> A.MatchArm:
        tok = self._consume(TokenType.IDENTIFIER, "Expected a variant name or '_'")
        # `_` is an ordinary identifier everywhere else, so the catch-all is
        # recognised by name here rather than by a token of its own.
        if tok.lexeme == "_":
            variant = None
        else:
            # Qualified in a pattern too. The subject's enum is known here, so
            # the short form could be allowed, but then a name would mean one
            # thing in an arm and another everywhere else.
            variant = self._qualified(tok)
        bindings: List[str] = []
        if self._match(TokenType.LEFT_PAREN):
            if variant is None:
                raise ParseError("'_' cannot bind a payload", tok.line, tok.col)
            while True:
                b = self._consume(TokenType.IDENTIFIER, "Expected a name to bind")
                bindings.append(b.lexeme)
                if not self._match(TokenType.COMMA):
                    break
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after arm bindings")
        self._consume(TokenType.FAT_ARROW, "Expected '=>' after the arm pattern")
        body = self._block()
        return A.MatchArm(variant, bindings, body, line=tok.line, col=tok.col)

    def _block(self) -> List[A.Stmt]:
        self._consume(TokenType.LEFT_BRACE, "Expected '{' to start block")
        stmts: List[A.Stmt] = []
        while not self._check(TokenType.RIGHT_BRACE):
            stmts.append(self._declaration())
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after block")
        return stmts

    def _declaration(self) -> A.Stmt:
        if self._match(TokenType.LET):
            return self._var_decl()
        return self._statement()

    def _var_decl(self) -> A.VarDecl:
        name_tok = self._consume(TokenType.IDENTIFIER, "Expected variable name")
        type_name: Optional[str] = None
        init: Optional[A.Expr] = None
        if self._match(TokenType.COLON):
            type_name = self._type_name()
        if self._match(TokenType.EQUAL):
            init = self._expression()
        self._consume(TokenType.SEMICOLON, "Expected ';' after variable declaration")
        return A.VarDecl(name_tok.lexeme, type_name, init, line=name_tok.line, col=name_tok.col)

    def _assign_or_expr(self) -> A.Stmt:
        """Parse `expr` or `expr = value`, leaving the terminator to the caller.

        A for-loop's init clause ends at ';' and its step clause at ')', so
        unlike a statement they cannot assume which token terminates them.
        """
        expr = self._expression()
        if self._match(TokenType.EQUAL):
            eq_tok = self._previous()
            value = self._expression()
            return A.Assign(expr, value, line=eq_tok.line, col=eq_tok.col)
        return A.ExprStmt(expr, line=expr.line, col=expr.col)

    def _for_init(self) -> Optional[A.Stmt]:
        if self._match(TokenType.SEMICOLON):
            return None
        if self._match(TokenType.LET):
            return self._var_decl()  # consumes its own ';'
        stmt = self._assign_or_expr()
        self._consume(TokenType.SEMICOLON, "Expected ';' after for-loop initializer")
        return stmt

    def _for_step(self) -> Optional[A.Stmt]:
        if self._check(TokenType.RIGHT_PAREN):
            return None
        return self._assign_or_expr()

    def _statement(self) -> A.Stmt:
        if self._match(TokenType.PRINT):
            tok = self._previous()
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'print'")
            expr = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after print expression")
            self._consume(TokenType.SEMICOLON, "Expected ';' after print statement")
            return A.Print(expr, line=tok.line, col=tok.col)
        if self._match(TokenType.PRINTLN):
            tok = self._previous()
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'println'")
            expr = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after println expression")
            self._consume(TokenType.SEMICOLON, "Expected ';' after println statement")
            return A.PrintLn(expr, line=tok.line, col=tok.col)
        if self._match(TokenType.VM_ASM):
            kw_tok = self._previous()
            return self._vm_asm_block(kw_tok)
        if self._match(TokenType.RETURN):
            tok = self._previous()
            value: Optional[A.Expr] = None
            if not self._check(TokenType.SEMICOLON):
                value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after return value")
            return A.Return(value, line=tok.line, col=tok.col)
        if self._match(TokenType.MATCH):
            return self._match_stmt(self._previous())
        if self._match(TokenType.IF):
            tok = self._previous()
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'if'")
            cond = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after condition")
            then_block = self._block()
            else_block = None
            if self._match(TokenType.ELSE):
                else_block = self._block()
            return A.If(cond, then_block, else_block, line=tok.line, col=tok.col)
        if self._match(TokenType.WHILE):
            tok = self._previous()
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'while'")
            cond = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after condition")
            body = self._block()
            return A.While(cond, body, line=tok.line, col=tok.col)
        if self._match(TokenType.FOR):
            tok = self._previous()
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'for'")
            init = self._for_init()
            cond: Optional[A.Expr] = None
            if not self._check(TokenType.SEMICOLON):
                cond = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after for-loop condition")
            step = self._for_step()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after for-loop clauses")
            body = self._block()
            return A.For(init, cond, step, body, line=tok.line, col=tok.col)
        if self._match(TokenType.BREAK):
            tok = self._previous()
            self._consume(TokenType.SEMICOLON, "Expected ';' after 'break'")
            return A.Break(line=tok.line, col=tok.col)
        if self._match(TokenType.CONTINUE):
            tok = self._previous()
            self._consume(TokenType.SEMICOLON, "Expected ';' after 'continue'")
            return A.Continue(line=tok.line, col=tok.col)
        if self._check(TokenType.LEFT_BRACE):
            # A bare block, which exists only to introduce a scope.
            tok = self._peek()
            return A.Block(self._block(), line=tok.line, col=tok.col)
        expr = self._expression()
        if self._match(TokenType.EQUAL):
            eq_tok = self._previous()
            value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after assignment")
            return A.Assign(expr, value, line=eq_tok.line, col=eq_tok.col)
        self._consume(TokenType.SEMICOLON, "Expected ';' after expression")
        return A.ExprStmt(expr, line=expr.line, col=expr.col)

    def _expression(self) -> A.Expr:
        return self._or()

    def _or(self) -> A.Expr:
        expr = self._and()
        while self._match(TokenType.OR_OR):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._and()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _and(self) -> A.Expr:
        expr = self._bitor()
        while self._match(TokenType.AND_AND):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._bitor()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _bitor(self) -> A.Expr:
        expr = self._bitxor()
        while self._match(TokenType.PIPE):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._bitxor()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _bitand(self) -> A.Expr:
        expr = self._equality()
        while self._match(TokenType.AMP):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._equality()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _bitxor(self) -> A.Expr:
        expr = self._bitand()
        while self._match(TokenType.CARET):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._bitand()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _equality(self) -> A.Expr:
        expr = self._comparison()
        while self._match(TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._comparison()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _comparison(self) -> A.Expr:
        expr = self._shift()
        while self._match(TokenType.GREATER, TokenType.GREATER_EQUAL, TokenType.LESS, TokenType.LESS_EQUAL):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._shift()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _shift(self) -> A.Expr:
        expr = self._term()
        while self._match(TokenType.SHL, TokenType.SHR):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._term()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _term(self) -> A.Expr:
        expr = self._factor()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._factor()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _factor(self) -> A.Expr:
        expr = self._unary()
        while self._match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op_tok = self._previous()
            op = op_tok.lexeme
            right = self._unary()
            expr = A.Binary(expr, op, right, line=op_tok.line, col=op_tok.col)
        return expr

    def _unary(self) -> A.Expr:
        # Parsed for any operand; sema/codegen narrow it to identifiers and indexing.
        if self._match(TokenType.AT):
            tok = self._previous()
            target = self._unary()
            return A.AddressOf(target, line=tok.line, col=tok.col)
        if self._match(TokenType.BANG, TokenType.MINUS, TokenType.TILDE):
            tok = self._previous()
            op = tok.lexeme
            right = self._unary()
            return A.Unary(op, right, line=tok.line, col=tok.col)
        return self._call()

    def _call(self) -> A.Expr:
        expr = self._primary()
        while True:
            if isinstance(expr, A.Identifier) and self._match(TokenType.LEFT_PAREN):
                paren_tok = self._previous()
                args: List[A.Expr] = []
                if not self._check(TokenType.RIGHT_PAREN):
                    while True:
                        args.append(self._expression())
                        if not self._match(TokenType.COMMA):
                            break
                self._consume(TokenType.RIGHT_PAREN, "Expected ')' after arguments")
                expr = A.Call(expr.name, args, line=paren_tok.line, col=paren_tok.col)
                continue
            # Any expression may be the base, so `arr[i][j]` chains.
            if self._match(TokenType.LEFT_BRACKET):
                bracket_tok = self._previous()
                index_expr = self._expression()
                self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after index expression")
                expr = A.Index(expr, index_expr, line=bracket_tok.line, col=bracket_tok.col)
                continue
            if self._match(TokenType.DOT):
                field_tok = self._consume(TokenType.IDENTIFIER, "Expected field name after '.'")
                expr = A.FieldAccess(expr, field_tok.lexeme, line=field_tok.line, col=field_tok.col)
                continue
            break
        return expr

    def _struct_literal(self, name_tok: Token) -> A.StructLit:
        self._consume(TokenType.LEFT_BRACE, "Expected '{' to start struct literal")
        inits: List[A.FieldInit] = []
        while not self._check(TokenType.RIGHT_BRACE):
            f_tok = self._consume(TokenType.IDENTIFIER, "Expected field name in struct literal")
            self._consume(TokenType.COLON, "Expected ':' after field name")
            value = self._expression()
            inits.append(A.FieldInit(f_tok.lexeme, value, line=f_tok.line, col=f_tok.col))
            if not self._match(TokenType.COMMA):
                break
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after struct literal fields")
        return A.StructLit(name_tok.lexeme, inits, line=name_tok.line, col=name_tok.col)

    def _vm_asm_block(self, kw_tok: Token) -> A.Stmt:
        self._consume(TokenType.LEFT_BRACE, "Expected '{' after 'vm_asm'")
        lines = []
        current_parts = []
        # The _is_at_end() guard matters: _advance() stops incrementing at EOF,
        # so without it an unterminated block spins forever.
        while not self._check(TokenType.RIGHT_BRACE) and not self._is_at_end():
            tok = self._advance()
            if tok.type == TokenType.SEMICOLON:
                current_parts.append(tok.lexeme)
                line = " ".join(current_parts).strip()
                if line:
                    lines.append(line)
                current_parts = []
            else:
                current_parts.append(tok.lexeme)
        # Anything still pending never met its ';'. Dropping it would silently
        # delete an instruction, so it is an error like any other malformed one.
        if current_parts:
            trailing = " ".join(current_parts).strip()
            raise ParseError(
                f"Expected ';' after vm_asm instruction '{trailing}'",
                kw_tok.line, kw_tok.col,
            )
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after vm_asm block")
        code = "\n".join(lines)
        return A.VmAsm(code, line=kw_tok.line, col=kw_tok.col)

    def _primary(self) -> A.Expr:
        if self._match(TokenType.FALSE):
            tok = self._previous()
            return A.Literal(False, line=tok.line, col=tok.col)
        if self._match(TokenType.TRUE):
            tok = self._previous()
            return A.Literal(True, line=tok.line, col=tok.col)
        if self._match(TokenType.NULL):
            tok = self._previous()
            return A.Literal(None, line=tok.line, col=tok.col)
        if self._match(TokenType.NUMBER):
            tok = self._previous()
            return A.Literal(tok.literal, line=tok.line, col=tok.col)
        if self._match(TokenType.FLOAT_NUMBER):
            tok = self._previous()
            return A.Literal(tok.literal, line=tok.line, col=tok.col)
        if self._match(TokenType.STRING):
            tok = self._previous()
            return A.Literal(tok.literal, line=tok.line, col=tok.col)
        if self._match(TokenType.IDENTIFIER):
            tok = self._previous()
            if self._check(TokenType.COLON_COLON):
                # `Enum::Variant` is one name, so a call on it lands in _call
                # as an ordinary Call and sema resolves it like any other.
                return A.Identifier(self._qualified(tok), line=tok.line, col=tok.col)
            # `Name { ... }` is a struct literal. This is unambiguous because
            # every condition in the language is parenthesized, so an
            # identifier is never directly followed by a block.
            if self._check(TokenType.LEFT_BRACE):
                return self._struct_literal(tok)
            return A.Identifier(tok.lexeme, line=tok.line, col=tok.col)
        if self._match(TokenType.LEFT_PAREN):
            expr = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after expression")
            return expr
        tok = self._peek()
        raise ParseError("Expected expression", tok.line, tok.col)
