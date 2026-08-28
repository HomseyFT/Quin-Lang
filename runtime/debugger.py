"""Execution control and inspection for a running QuinVM.

The VM offers one control point -- a hook called before each instruction -- and
everything here is built on it: breakpoints are a pc set the hook consults,
stepping is a comparison against the source line and call depth the step began
at, and inspection reads the frame and heap the VM already holds.

There is no I/O in this module. A front end supplies an `on_stop` callback and
blocks inside it for as long as it likes; when it returns, execution resumes in
whatever mode it selected. That keeps the whole state machine testable without
a terminal, which is how tests/test_debugger.py drives it.

Reading a value means reading VM internals -- slots, heap words, string
objects -- so this module uses them directly rather than growing a parallel
accessor for each. That is the one coupling it accepts, and the reason it lives
in the runtime package beside the VM rather than beside the compiler.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Tuple

from compiler.bytecode import SourceMap
from runtime.vm import (
    HEADER_BYTES,
    KIND_STRUCT,
    LocalInfo,
    QuinVM,
    VMError,
    bits_to_float,
    format_float,
    to_signed,
)

# How deep a struct is expanded before it is shown as a bare address. A linked
# list is the ordinary case, and without a limit a cyclic one would not return.
MAX_STRUCT_DEPTH = 3


class DebuggerError(Exception):
    """A command that cannot be carried out -- an unknown function, a line with
    no code. Reported to the user; never fatal to the session."""


class Quit(Exception):
    """Raised out of the hook to abandon the run. The front end asked to stop,
    so the program does not finish and has no exit value."""


class ResumeNotChosen(RuntimeError):
    """A front end returned from on_stop without saying how to resume.

    Its own bug, not the debugged program's, which is why it is not a
    DebuggerError: nothing the user typed can cause it and no front end should
    catch it.
    """


class Mode(Enum):
    """What the hook should do at the next instruction."""
    RUN = auto()        # only breakpoints stop us
    ENTRY = auto()      # stop immediately, before anything executes
    STEP_IN = auto()    # stop at the next line, entering calls
    STEP_OVER = auto()  # stop at the next line in this frame or its caller
    FINISH = auto()     # stop when this frame returns


class StopReason(Enum):
    ENTRY = auto()
    BREAKPOINT = auto()
    STEP = auto()
    PAUSE = auto()
    FAULT = auto()


@dataclass
class Breakpoint:
    id: int
    pc: int
    function: str
    file: str
    line: int
    enabled: bool = True
    hits: int = 0


@dataclass(frozen=True)
class FrameView:
    """One activation, as the debugger reports it.

    `locals` is the live slot list, not a copy: inspecting a suspended caller
    has to see what the VM will resume with.
    """
    depth: int          # 0 is innermost
    fn_index: int
    function: str
    file: str
    pc: int
    line: Optional[int]
    col: Optional[int]
    locals: List[int]


class ValueKind(Enum):
    """What a value is made of, which is what a front end needs to render it."""
    SCALAR = auto()     # nothing inside: int, bool, float, str, null, an address
    STRUCT = auto()     # named fields
    VARIANT = auto()    # an enum variant, whose payload is positional
    ARRAY = auto()      # N consecutive slots of one type


@dataclass(frozen=True)
class Value:
    """One value, described rather than rendered.

    Two front ends want the same information in different shapes: a terminal
    flattens the whole thing onto one line, while DAP hands the client a handle
    and expands one level per click. So this says what the value is and where
    its children live, and leaves rendering to whoever asked.

    `summary` is the one-line form with children elided -- `Node {...}` -- which
    is what DAP shows beside the expander. `type_name` is the declared type;
    `object_name` is what the object's own layout calls itself, which for a
    variant is the qualified `Result::Ok` and differs from the declared `Result`.
    """
    summary: str
    type_name: str
    kind: ValueKind = ValueKind.SCALAR
    address: int = 0            # the heap object, for STRUCT and VARIANT
    object_name: str = ""
    elements: Tuple[Tuple[str, "Value"], ...] = ()   # ARRAY, read eagerly

    @property
    def expandable(self) -> bool:
        return self.kind is not ValueKind.SCALAR


@dataclass
class Stop:
    """Why execution paused, and where."""
    reason: StopReason
    frame: FrameView
    breakpoint: Optional[Breakpoint] = None
    error: Optional[VMError] = None


class Debugger:
    """Breakpoints, stepping and inspection over one compiled program."""

    def __init__(self, program, on_stop: Callable[["Debugger", QuinVM, Stop], None] = None):
        self.program = program
        self.source_map: SourceMap = program.source_map
        self.functions = program.functions
        self.structs = program.structs
        self.on_stop = on_stop or self._run_to_completion

        self.breakpoints: Dict[int, Breakpoint] = {}
        self._by_pc: Dict[int, Breakpoint] = {}
        self._next_id = 1

        self._mode: Optional[Mode] = Mode.ENTRY
        self._from_line: Optional[int] = None
        self._from_depth = 0

        # Set from another thread to interrupt a running program. An Event
        # rather than a bool: the writer and the reader are different threads,
        # and this says so instead of leaning on the GIL for correctness.
        self._pause_requested = threading.Event()

        self._ranges = self._function_ranges()

    @staticmethod
    def _run_to_completion(dbg: "Debugger", vm: QuinVM, stop: "Stop") -> None:
        """The default front end: no one is watching, so keep going.

        Spelled out rather than left as a no-op, because a callback that
        returns without choosing is now an error -- and it should be, since
        every other caller has a real decision to make here.
        """
        dbg.resume(Mode.RUN, vm)

    # -- program layout --------------------------------------------------

    def _function_ranges(self) -> Dict[int, Tuple[int, int]]:
        """Function index -> the half-open pc range it occupies.

        Functions are emitted back to back, so each one runs until the next
        one starts. The ranges are what make a line number unambiguous: the
        source map covers the whole program, where line 30 belongs to
        std/math.ql and to the user's file alike.
        """
        order = sorted(range(len(self.functions)),
                       key=lambda i: self.functions[i].entry_pc)
        ranges: Dict[int, Tuple[int, int]] = {}
        end_of_code = len(self.program.code)
        for position, index in enumerate(order):
            start = self.functions[index].entry_pc
            following = order[position + 1] if position + 1 < len(order) else None
            end = self.functions[following].entry_pc if following is not None else end_of_code
            ranges[index] = (start, end)
        return ranges

    def _entry_file(self) -> str:
        """The file the user compiled, which is the one `break 12` means."""
        for fn in self.functions:
            if fn.name == "main":
                return fn.source_file
        return self.functions[0].source_file if self.functions else ""

    def _functions_in_file(self, wanted: str) -> List[int]:
        """Every function declared in `wanted`, matched by path suffix so that
        `math.ql`, `std/math.ql` and the absolute path all name the same file."""
        matches = []
        for i, fn in enumerate(self.functions):
            path = fn.source_file
            if path == wanted or path.endswith("/" + wanted.lstrip("./")):
                matches.append(i)
        return matches

    # -- breakpoints -----------------------------------------------------

    def break_at_function(self, name: str) -> Breakpoint:
        for i, fn in enumerate(self.functions):
            if fn.name == name:
                pos = self.source_map.lookup(fn.entry_pc)
                return self._add(fn.entry_pc, i, pos[0] if pos else 0)
        raise DebuggerError(f"no function named '{name}'")

    def break_at_line(self, line: int, file: str = "") -> Breakpoint:
        """Stop at `line` of `file`, or of the compiled file when none is given.

        A line with no code of its own -- blank, a comment, a closing brace --
        moves forward to the next line that has some, the way every debugger
        does, rather than silently never firing.
        """
        wanted = file or self._entry_file()
        indices = self._functions_in_file(wanted)
        if not indices:
            raise DebuggerError(f"no source file matching '{wanted}'")

        for index in self._ordered(indices):
            start, end = self._ranges[index]
            pc = self.source_map.first_pc_on_line(line, start, end)
            if pc is not None:
                return self._add(pc, index, line)

        # Nothing on that exact line: take the next line in the file that has
        # code, so `break 7` on a blank line means what the user meant.
        candidates = []
        for index in indices:
            start, end = self._ranges[index]
            candidates.extend(l for l in self.source_map.lines_in(start, end) if l > line)
        if not candidates:
            raise DebuggerError(f"no code at or after line {line} in {wanted}")
        return self.break_at_line(min(candidates), file)

    def _ordered(self, indices: List[int]) -> List[int]:
        return sorted(indices, key=lambda i: self.functions[i].entry_pc)

    def _add(self, pc: int, fn_index: int, line: int) -> Breakpoint:
        existing = self._by_pc.get(pc)
        if existing is not None:
            return existing
        bp = Breakpoint(self._next_id, pc, self.functions[fn_index].name,
                        self.functions[fn_index].source_file, line)
        self._next_id += 1
        self.breakpoints[bp.id] = bp
        self._by_pc[pc] = bp
        return bp

    def clear_breakpoints(self) -> None:
        """Drop every breakpoint.

        For a front end whose breakpoint set is declarative -- DAP sends the
        whole desired list for a file and expects it to replace what was there
        -- rebuilding from empty is the only way to avoid aliasing: two
        requested lines that resolve to the same pc share one Breakpoint here,
        so removing them one at a time can take a third one's with it.
        """
        self.breakpoints.clear()
        self._by_pc.clear()

    def remove(self, bp_id: int) -> None:
        bp = self.breakpoints.pop(bp_id, None)
        if bp is None:
            raise DebuggerError(f"no breakpoint {bp_id}")
        self._by_pc.pop(bp.pc, None)

    def set_enabled(self, bp_id: int, enabled: bool) -> Breakpoint:
        bp = self.breakpoints.get(bp_id)
        if bp is None:
            raise DebuggerError(f"no breakpoint {bp_id}")
        bp.enabled = enabled
        return bp

    # -- running ---------------------------------------------------------

    def resume(self, mode: Mode, vm: QuinVM, frame_depth: int = 0) -> None:
        """Choose what happens after the front end returns from on_stop.

        `frame_depth` names which activation the mode is relative to, so that
        `finish` on a frame the user selected runs until *that* one returns
        rather than the innermost. Stepping is always relative to frame 0,
        which is what its caller passes.
        """
        self._mode = mode
        self._from_depth = len(vm.call_stack) - frame_depth
        pos = self.source_map.lookup(vm.pc)
        self._from_line = pos[0] if pos else None

    def run(self, vm: QuinVM) -> int:
        """Run to completion under the debugger, returning main's exit value.

        A fault stops one last time before it propagates. The VM does not unwind
        its own frames when it raises, so the whole call stack is still there to
        be inspected -- which is the moment the information is most wanted.
        """
        vm.hook = self._on_instruction
        try:
            return vm.run_main()
        except VMError as e:
            self._stop(vm, Stop(StopReason.FAULT, self.frames(vm)[0], error=e))
            raise
        finally:
            vm.hook = None

    def pause(self) -> None:
        """Ask a running program to stop at the next instruction.

        Safe to call from another thread, and from any mode: the check below
        runs before the breakpoint lookup, so it is reached even while the
        program is running freely.
        """
        self._pause_requested.set()

    def _on_instruction(self, vm: QuinVM) -> None:
        if self._pause_requested.is_set():
            self._pause_requested.clear()
            self._stop(vm, Stop(StopReason.PAUSE, self.frames(vm)[0]))
            return

        bp = self._by_pc.get(vm.pc)
        if bp is not None and bp.enabled:
            bp.hits += 1
            self._stop(vm, Stop(StopReason.BREAKPOINT, self.frames(vm)[0], breakpoint=bp))
            return

        if self._mode is Mode.RUN:
            return
        if self._mode is Mode.ENTRY:
            self._stop(vm, Stop(StopReason.ENTRY, self.frames(vm)[0]))
            return

        depth = len(vm.call_stack)
        pos = self.source_map.lookup(vm.pc)
        line = pos[0] if pos else None

        if self._mode is Mode.FINISH:
            should_stop = depth < self._from_depth
        elif self._mode is Mode.STEP_OVER:
            # Deeper means we are inside a call this step is meant to pass over.
            should_stop = depth < self._from_depth or (
                depth == self._from_depth and line != self._from_line)
        else:  # STEP_IN
            should_stop = depth != self._from_depth or line != self._from_line

        if should_stop:
            self._stop(vm, Stop(StopReason.STEP, self.frames(vm)[0]))

    def _stop(self, vm: QuinVM, stop: Stop) -> None:
        """Hand control to the front end, which must choose what happens next.

        The mode is cleared before the callback and checked after it, so a
        front end that returns without choosing gets an error instead of a
        silent continue. Defaulting to RUN reads as harmless and is not: a
        `step` that quietly became a `continue` looks like a breakpoint that
        failed to fire, and the further the front end is from the VM -- another
        thread, another process -- the harder that is to see.
        """
        self._mode = None
        self.on_stop(self, vm, stop)
        if self._mode is None:
            raise ResumeNotChosen(
                "on_stop returned without calling Debugger.resume(); "
                "the debugger cannot guess whether to step or continue"
            )

    # -- inspection ------------------------------------------------------

    def frames(self, vm: QuinVM) -> List[FrameView]:
        """The call stack, innermost first.

        Built the way VMError's backtrace is: `vm.pc` is the instruction about
        to run, and a suspended caller resumes at its saved return_pc, which
        puts its CALL one before that.
        """
        entries = [(vm.current_fn, vm.pc, vm.locals)]
        for frame in reversed(vm.call_stack):
            entries.append((frame.fn_index, frame.return_pc - 1, frame.locals))

        views = []
        for depth, (fn_index, pc, slots) in enumerate(entries):
            pos = self.source_map.lookup(pc)
            fn = self.functions[fn_index] if 0 <= fn_index < len(self.functions) else None
            views.append(FrameView(
                depth=depth,
                fn_index=fn_index,
                function=fn.name if fn else f"<function {fn_index}>",
                file=fn.source_file if fn else "",
                pc=pc,
                line=pos[0] if pos else None,
                col=pos[1] if pos else None,
                locals=slots,
            ))
        return views

    def locals_of(self, frame: FrameView) -> Tuple[LocalInfo, ...]:
        if 0 <= frame.fn_index < len(self.functions):
            return self.functions[frame.fn_index].locals_
        return ()

    def lookup_name(self, frame: FrameView, name: str) -> List[LocalInfo]:
        """Every slot in `frame` declared with `name`.

        More than one means the name is shadowed. The slot table carries no
        scope ranges, so which of them is live at this pc is not knowable here;
        the caller is told about all of them rather than shown a confident
        guess at the wrong one.
        """
        return [li for li in self.locals_of(frame) if li.name == name]

    def format_local(self, vm: QuinVM, frame: FrameView, info: LocalInfo) -> str:
        """One line, everything expanded.

        What a terminal front end shows, and the reason MAX_STRUCT_DEPTH still
        exists: there is no click to expand one more level, so the whole value
        has to be on the line and something has to stop a cyclic list.
        """
        return self._flatten(vm, self.describe_local(vm, frame, info), 0)

    def describe_local(self, vm: QuinVM, frame: FrameView, info: LocalInfo) -> Value:
        return self._describe_slots(vm, frame.locals, info.slot,
                                    info.type_name, info.words)

    def children_of(self, vm: QuinVM, value: Value) -> List[Tuple[str, Value]]:
        """One level of `value`, and only one.

        Nothing here recurses, which is what makes a cyclic structure safe to
        walk: a front end that expands on demand can follow `next.next.next`
        forever, one request at a time.
        """
        if value.kind is ValueKind.ARRAY:
            return list(value.elements)
        if value.address == 0:
            return []
        layout = self._layout_at(vm, value.address)
        if layout is None:
            return []
        children = []
        for index, field in enumerate(layout.fields):
            # A variant's payload is positional -- its fields are named _0, _1
            # -- and nothing in the language can refer to one by name, so it is
            # numbered here the way an array element is.
            name = f"[{index}]" if value.kind is ValueKind.VARIANT else field.name
            children.append((name, self._describe_field(
                vm, value.address + field.offset * 2, field.type_name)))
        return children

    # -- value decoding --------------------------------------------------

    def _slot(self, slots: List[int], index: int) -> int:
        return slots[index] if 0 <= index < len(slots) else 0

    def _describe_slots(self, vm: QuinVM, slots: List[int], slot: int,
                        type_name: str, words: int) -> Value:
        """The value occupying `words` slots from `slot`."""
        if type_name.endswith("]"):
            base = type_name[:type_name.index("[")]
            elements = tuple(
                (f"[{i}]", self._describe_slots(vm, slots, slot + i, base, 1))
                for i in range(words))
            summary = "[" + ", ".join(v.summary for _, v in elements) + "]"
            return Value(summary, type_name, ValueKind.ARRAY, elements=elements)
        if type_name == "float":
            low = self._slot(slots, slot)
            high = self._slot(slots, slot + 1)
            return Value(format_float(bits_to_float(low | (high << 16))), type_name)
        return self._describe_word(vm, self._slot(slots, slot), type_name)

    def _describe_word(self, vm: QuinVM, word: int, type_name: str) -> Value:
        if type_name == "bool":
            return Value("true" if word else "false", type_name)
        if type_name == "str":
            if word == 0:
                return Value("null", type_name)
            try:
                return Value('"' + vm._string_text(word) + '"', type_name)
            except (VMError, IndexError, UnicodeDecodeError):
                return Value(f"<unreadable str at {word}>", type_name)
        if type_name in ("int", "heapptr", "ptr"):
            return Value(str(to_signed(word)), type_name)
        return self._describe_object(vm, word, type_name)

    def _describe_object(self, vm: QuinVM, ref: int, type_name: str) -> Value:
        """A heap reference, read through its own header.

        The layout comes from what the object says it is rather than from the
        declared type, so a wrong guess shows as an address instead of as the
        wrong fields.
        """
        if ref == 0:
            return Value("null", type_name)
        layout = self._layout_at(vm, ref)
        if layout is None or not layout.fields:
            if layout is not None and layout.is_variant:
                # A variant carrying nothing is written as a bare name, so that
                # is how it reads back -- and there is nothing to expand.
                return Value(layout.name, type_name, object_name=layout.name)
            return Value(f"<{type_name} at {ref}>", type_name)
        if layout.is_variant:
            return Value(f"{layout.name}(\u2026)", type_name, ValueKind.VARIANT,
                         address=ref, object_name=layout.name)
        return Value(f"{layout.name} {{\u2026}}", type_name, ValueKind.STRUCT,
                     address=ref, object_name=layout.name)

    def _describe_field(self, vm: QuinVM, addr: int, type_name: str) -> Value:
        try:
            if type_name == "float":
                bits = vm._read_word(addr) | (vm._read_word(addr + 2) << 16)
                return Value(format_float(bits_to_float(bits)), type_name)
            return self._describe_word(vm, vm._read_word(addr), type_name)
        except (IndexError, VMError):
            return Value("<unreadable>", type_name)

    def _flatten(self, vm: QuinVM, value: Value, depth: int) -> str:
        if value.kind is ValueKind.SCALAR:
            return value.summary
        if value.kind is ValueKind.ARRAY:
            # An array is one value, not a level of nesting: its elements are
            # what a depth cap is meant to let you see.
            children = self.children_of(vm, value)
            return "[" + ", ".join(self._flatten(vm, c, depth)
                                   for _, c in children) + "]"
        if depth >= MAX_STRUCT_DEPTH:
            return f"<{value.object_name} at {value.address}>"
        children = self.children_of(vm, value)
        rendered = [self._flatten(vm, child, depth + 1) for _, child in children]
        if value.kind is ValueKind.VARIANT:
            return f"{value.object_name}(" + ", ".join(rendered) + ")"
        named = (f"{name}: {text}"
                 for (name, _), text in zip(children, rendered))
        return f"{value.object_name} {{ " + ", ".join(named) + " }"

    def _layout_at(self, vm: QuinVM, ref: int):
        """The struct layout of the object at `ref`, read from its heap header
        rather than from the declared type, so a wrong guess shows as unknown
        instead of as the wrong fields."""
        hdr = ref - HEADER_BYTES
        try:
            if hdr < 0 or vm._kind(hdr) != KIND_STRUCT:
                return None
            type_id = vm._detail(hdr)
        except IndexError:
            return None
        if 0 <= type_id < len(self.structs):
            return self.structs[type_id]
        return None
