"""S03 contract-test bootstrap.

Bytecode writes are switched off before any test or core module is imported, so pytest does not
drop __pycache__ files into the worktree or the read-only pinned core on PYTHONPATH. Only this
file's own compiled copy can be written (it is imported before the flag is set); the sibling
.gitignore keeps it out of git.
"""

import sys

sys.dont_write_bytecode = True
