import argparse
from pathlib import Path
from .resolver import ImportResolver, ResolveError
from .sema import SemanticAnalyzer, SemanticError
from .codegen_vm import CodeGenVM, CodegenError
from .debug import debug
from runtime.vm import QuinVM, VMError
import sys


# A program's own return value can still be 2 or 3 -- main returns a byte, so
# no code is reserved from it. Moving the tool's errors off 1 just puts them on
# values a program is far less likely to pick deliberately, and stderr remains
# the only certain signal. 2 doubles as argparse's exit for a bad command line;
# both mean "nothing ran".
EXIT_COMPILE_ERROR = 2
EXIT_RUNTIME_ERROR = 3


def process_exit_code(value: int) -> int:
    """Narrow main's 16-bit return value to the 8 bits an exit status carries.

    POSIX truncates this way regardless, but Windows exit codes are 32 bits
    wide and would otherwise report -1 as 4294967295.
    """
    return value & 0xFF


def main():
    ap = argparse.ArgumentParser(description="QuinLang VM compiler/executor")
    ap.add_argument("source", type=Path, help="Source .ql file")
    ap.add_argument("--debug", action="store_true",
                    help="run under the interactive debugger")
    args = ap.parse_args()

    std_path = Path(__file__).parent.parent / "std"

    try:
        resolver = ImportResolver(std_path)
        resolved = resolver.resolve(args.source)
        ast = resolved.program

        ctx = SemanticAnalyzer().analyze(ast)
        codegen = CodeGenVM()
        program = codegen.generate(ast, ctx)
    except ResolveError as e:
        print(f"Import error: {e}", file=sys.stderr)
        sys.exit(EXIT_COMPILE_ERROR)
    except SemanticError as e:
        print(f"Semantic error: {e}", file=sys.stderr)
        sys.exit(EXIT_COMPILE_ERROR)
    except CodegenError as e:
        print(f"Codegen error: {e}", file=sys.stderr)
        sys.exit(EXIT_COMPILE_ERROR)

    # Warnings go to stderr so piping stdout stays clean, and change neither
    # the exit code nor whether the program runs.
    for warning in ctx.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    vm = QuinVM(program.code, program.functions, program.strings,
                program.structs, program.source_map)
    if args.debug:
        # The debugger reports the fault itself, having first let the user look
        # around the frames it happened in, so the same error still exits 3.
        try:
            exit_value = debug(program, vm)
        except VMError:
            sys.exit(EXIT_RUNTIME_ERROR)
        # Quitting the session means the program never finished. Nothing failed,
        # so this is not a runtime error; there is simply no value to report.
        sys.exit(0 if exit_value is None else process_exit_code(exit_value))

    try:
        exit_value = vm.run_main()
    except VMError as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        sys.exit(EXIT_RUNTIME_ERROR)

    sys.exit(process_exit_code(exit_value))


if __name__ == "__main__":
    main()
