"""Source file to runnable program, in one call.

The front end is five passes that always run in the same order, and every entry
point needs all of them: the CLI, the debugger, the DAP adapter, the tests. This
is that sequence, named once so a third front end does not become a third copy
of it.

Errors are raised, not printed. What to do with a compile failure differs by
caller -- stderr and an exit code for the CLI, a failed `launch` response for
the adapter -- so this reports and lets them decide.
"""

from __future__ import annotations

from pathlib import Path

from .codegen_vm import CodeGenVM, CodegenError
from .resolver import ImportResolver, ResolveError
from .sema import SemanticAnalyzer, SemanticError
from .serialize import BytecodeError, is_bytecode, read_program

# Every way an entry point can fail to get a runnable program. Lexer and parser
# errors arrive wrapped in ResolveError, because the resolver is what reads
# files; an unloadable .qlc belongs here for the same reason the others do --
# nothing ran, and every caller wants to say so the same way.
CompileError = (ResolveError, SemanticError, CodegenError, BytecodeError)

STD_PATH = Path(__file__).parent.parent / "std"


def describe_error(error: Exception) -> str:
    """A compile error with the label the CLI would give it."""
    labels = {ResolveError: "Import error", SemanticError: "Semantic error",
              CodegenError: "Codegen error", BytecodeError: "Bytecode error"}
    for kind, label in labels.items():
        if isinstance(error, kind):
            return f"{label}: {error}"
    return str(error)


def compile_path(source: Path, std_path: Path = None):
    """Compile a .ql file to a CompiledProgram, with its warnings.

    Returns `(program, warnings)`. Warnings do not stop a program running, so
    they travel beside the result rather than as an exception.
    """
    resolved = ImportResolver(std_path or STD_PATH).resolve(Path(source))
    ctx = SemanticAnalyzer().analyze(resolved.program)
    return CodeGenVM().generate(resolved.program, ctx), list(ctx.warnings)


def program_for(source: Path, std_path: Path = None):
    """A runnable program from either a `.ql` source file or a `.qlc`.

    Dispatched on the file's first bytes rather than its name. What a file is
    is not the caller's to guess from a suffix, and a `.qlc` handed to the
    lexer would be reported as a syntax error in binary data.

    A loaded program has no warnings: they were reported when it was compiled,
    and re-reporting them at every run would be noise the user cannot act on.
    """
    if is_bytecode(source):
        return read_program(source), []
    return compile_path(source, std_path)
