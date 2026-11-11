"""S01 scaffold test bootstrap.

The pinned Hermes core is imported from a read-only reference tree via PYTHONPATH. Turning off
bytecode writes here, before any test module or core module is imported, keeps pytest and the
interpreter from dropping __pycache__ files into that tree or the worktree. Only this file's own
compiled copy can be written, because it is imported before the flag is set.
"""

import sys

sys.dont_write_bytecode = True
