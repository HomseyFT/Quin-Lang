"""A Debug Adapter Protocol server for QuinLang.

A third front end beside `compiler/debug.py`, speaking the protocol VS Code,
Neovim, Emacs and Zed already understand, so one implementation reaches all of
them. The state machine underneath is the same `runtime.debugger.Debugger` the
terminal client drives.
"""
