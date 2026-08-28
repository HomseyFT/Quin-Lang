-- QuinLang under nvim-dap.
--
-- Drop this in your config (or `dofile` it) and `:DapContinue` on an open .ql
-- file. Point `quinlang` at your checkout; nothing else needs configuring.

local dap = require("dap")

local quinlang = vim.fn.expand("~/Coding_Projects/QuinLang")

-- `.ql` is CodeQL's extension too. If you use both, key this off the directory
-- rather than the suffix, or drop this line and set the filetype by hand.
vim.filetype.add({ extension = { ql = "quinlang" } })

-- The adapter is spawned per session and speaks DAP over its stdin and stdout,
-- so `cwd` is what makes `python3 -m dap` importable -- not where the debugged
-- program runs.
dap.adapters.quinlang = {
  type = "executable",
  command = "python3",
  args = { "-m", "dap" },
  options = { cwd = quinlang },
}

-- Keyed by filetype, not by adapter name.
dap.configurations.quinlang = {
  {
    type = "quinlang",
    request = "launch",
    name = "Run the current file",
    program = "${file}",
    stopOnEntry = false,
    -- Read by argv(n). argv(0) is the program itself.
    args = {},
  },
}

-- A program run under the debugger sees an empty stdin: DAP has no reverse
-- request for reading a line, so read_line() reports end of input. Use the
-- terminal debugger for anything that reads:
--     python3 -m compiler.driver_vm --debug prog.ql
