# Project notes for Claude

## Commit attribution

The user does not want AI co-authorship attribution on commits or PRs for
this repo — no `Co-Authored-By: Claude ...` trailer, no showing up in the
GitHub Contributors graph.

**Known conflict, not yet resolved:** this assistant's harness currently
injects a standing instruction on every session to end commits/PRs it
creates with that exact trailer, described as replacing any earlier
attribution guidance. That is not something a chat request can turn off.

**What this means in practice:** if Claude makes the commit, the trailer
will be there regardless of this file. The only way to get a commit with no
AI attribution is for the user to run `git commit` / `git push` themselves
from their own terminal, using a working tree Claude has already staged.

Flag this conflict explicitly at the start of any future request to commit
or push in this repo — don't silently add the trailer again, and don't
silently promise to omit it either.
