---
trigger: always_on
---

# Skill: Context Keeper

## Purpose
To preserve the current state, architectural decisions, and "to-do" lists so the agent never loses progress between sessions.

## Commands
- "Save Context": Create or update a `MEMORY.md` file at the root.
- "Load Context": Read `MEMORY.md` to resume work exactly where we left off.

## Content to Capture
1. **Current Goal**: What are we building right now?
2. **Tech Decisions**: Why did we choose Firebase over Supabase?
3. **Pending Tasks**: What is the very next line of code to write?
4. **Known Bugs**: What should I not try to fix again?
