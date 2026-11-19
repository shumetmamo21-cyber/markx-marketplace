# Claude Code instructions for MarkX

Before doing anything in this repository:

1. Read **`AGENTS.md`**. It holds the rules for every AI agent on this project
   and applies to you in full.
2. Read **`MARKX_MASTER_BLUEPRINT.md`**, the single source of truth for MarkX.
3. Read **`docs/DEVELOPMENT_STATUS.md`** for the current state and the exact
   next task, then **`docs/DECISIONS.md`**.

Do not rely on conversation history from an earlier session. Everything a new
session needs is in those files and in the code.

Start every session from the latest `main` and work on your own new branch,
made from it for this session. Never merge into `main` without the founder's
written approval. Never touch the founder's
existing AWS servers or payment bot, never create paid resources, and never
commit secrets. The founder's working rules (mobile app only, the planning
Claude Project, plain-English reports, the three documents updated at the end
of every session) are in `AGENTS.md`, section 4a.
