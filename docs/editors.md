# Debugging QuinLang from an editor

`dap/` is a [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/)
server. Any DAP client can drive it, so breakpoints, stepping and variable
inspection are the same implementation everywhere — the one in
`runtime/debugger.py` that the terminal debugger also uses.

```bash
python3 -m dap                 # stdio; the client spawns this and speaks DAP
                               # over its stdin and stdout
python3 -m dap --server 4711   # TCP on 127.0.0.1, for a client that connects
                               # to an adapter already running
```

Run it from the repository root, or with the root on `PYTHONPATH`. There are no
dependencies to install.

## What the adapter supports

| | |
| --- | --- |
| Breakpoints | by line and by function, set before or during a run |
| Stepping | continue, step over, step into, step out, pause |
| Inspection | call stack, locals, struct and array expansion, hover, watch |
| Output | program output in the debug console, with the process exit code |

A line with no code of its own — blank, a comment, a closing brace — moves
forward to the next line that has some, and the client's marker follows.

**Reading input does not work under a debug adapter.** DAP has no reverse
request for it, so `read_line()` reports end of input rather than blocking on a
stdin nothing is attached to. Use the terminal debugger for a program that
reads:

```bash
python3 -m compiler.driver_vm --debug prog.ql
```

## Launch configuration

Three attributes, and only these three — the adapter honours what it declares:

| | |
| --- | --- |
| `program` | absolute path to the `.ql` file. Required. |
| `stopOnEntry` | stop before the first statement of `main`. Default `false`. |
| `args` | strings the program reads with `argv(n)`. `argv(0)` is the program itself. |

## VS Code

`docs/vscode/` is a complete extension with no build step. Link it into your
extensions directory and reload:

```bash
ln -s "$PWD/docs/vscode" ~/.vscode/extensions/quinlang-debug
```

It lives inside the repository on purpose: `adapter.py` finds the checkout three
directories up, so nothing needs configuring. If you copy the folder somewhere
else instead, set `QUINLANG_HOME` to your checkout.

Then open a `.ql` file and press F5. "Add Configuration…" offers a QuinLang
entry, or write one by hand:

```json
{
  "type": "quinlang",
  "request": "launch",
  "name": "Run the current file",
  "program": "${file}",
  "stopOnEntry": false,
  "args": []
}
```

**`.ql` is CodeQL's extension too.** If you have that extension installed, one
of them wins the file association. Renaming the language id here would not help
— the collision is over the suffix.

## Neovim

`docs/nvim-dap.lua` is a drop-in [nvim-dap](https://github.com/mfussenegger/nvim-dap)
configuration. Edit the path at the top to your checkout, then `:DapContinue` on
an open `.ql` file.

The same `.ql` caveat applies: the snippet claims the extension for QuinLang, so
key the filetype off the directory instead if you also write CodeQL.

## Anything else

Emacs (dape), Zed and any other DAP client need the same three facts: the
adapter is `python3 -m dap`, it speaks over stdio, and the launch request takes
the three attributes above. Nothing in the adapter is client-specific.
