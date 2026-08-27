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

# Every way the front end can reject a program. Lexer and parser errors arrive
# wrapped in ResolveError, because the resolver is what reads files.
CompileError = (ResolveError, SemanticError, CodegenError)

STD_PATH = Path(__file__).parent.parent / "std"


def describe_error(error: Exception) -> str:
    """A compile error with the label the CLI would give it."""
    labels = {ResolveError: "Import error", SemanticError: "Semantic error",
              CodegenError: "Codegen error"}
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
