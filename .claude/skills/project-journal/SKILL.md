---
name: project-journal
description: >
  Generates and incrementally updates a PROJECT_JOURNAL.md file that documents
  the full story of a project — actions taken, concepts used, key code blocks,
  errors faced and resolved — organized by project phases for interview
  preparation. Use this skill whenever the user asks to document their project,
  create interview prep notes, generate a project journal or log, update their
  project documentation, or asks anything like "document what we've done",
  "update the journal", "add this to the project docs", "prep me for interview
  questions about this project", or "what have we built so far". Also trigger
  when the user says "journal", "project log", "document progress", or
  "interview prep". This skill expects a plan.md and progress.md in the project
  root but can adapt if they're named differently or missing.
---

# Project Journal Skill

You maintain a living document called `PROJECT_JOURNAL.md` at the project root. This file tells the complete story of the project in a way that makes the developer interview-ready — they should be able to open it, skim it in 10 minutes, and confidently explain any part of the project to a technical or non-technical interviewer.

## Philosophy

The journal is not a commit log. It's not a changelog. It's the narrative a developer would tell in an interview: "Here's what we built, why we built it this way, what went wrong, how we fixed it, and what I learned." Write it in that spirit.

**Token efficiency matters.** Don't regenerate the whole file every time. Read what's already there, figure out what's new (by comparing against `progress.md` and recent work), and append or update only the new sections. If nothing meaningful has changed, say so and move on.

## How the journal is structured

```markdown
# Project Journal: [Project Name]

> One-liner: what this project does, in plain English.

## Tech Stack & Architecture
- Brief list of languages, frameworks, databases, APIs used
- High-level architecture (e.g., "React frontend → Express API → PostgreSQL")
- Why these choices were made (if known)

## Phase 1: [Phase Name from plan.md]

### What We Did
- Bullet summary of actions taken in this phase
- Keep it scannable — one line per action

### Key Concepts
Brief explanation of important concepts used in this phase. Think of it as
answering "can you explain how X works in your project?" Write just enough
that the developer can elaborate confidently from memory.

### Code Worth Discussing
```language
// Only include code blocks that are architecturally interesting,
// demonstrate a pattern, or solved a non-trivial problem.
// Add a one-line comment explaining WHY this code matters.
```

### Errors & Fixes
| Error | Root Cause | Fix |
|-------|-----------|-----|
| Brief error description | What actually caused it | How it was resolved |

(Skip this table if the phase had no notable errors.)

### Decisions & Trade-offs
- Any architectural or design decisions worth mentioning
- What alternatives were considered and why this path was chosen

---

## Phase 2: [Phase Name]
(same structure repeats)

---

## Lessons Learned
- Things that would be done differently next time
- Key takeaways from the project

## Quick-Fire Interview Answers
- **"What does your project do?"** → [one-sentence answer]
- **"What was the hardest part?"** → [one-sentence answer]
- **"What would you improve?"** → [one-sentence answer]
```

## Workflow

### First run (no PROJECT_JOURNAL.md exists yet)

1. Read `plan.md` to understand the project structure, phases, and goals
2. Read `progress.md` to understand what's been completed so far
3. Scan the codebase briefly — look at the directory structure, key config files (`package.json`, `requirements.txt`, `Cargo.toml`, etc.), and main entry points to understand the tech stack
4. Generate the full `PROJECT_JOURNAL.md` covering everything done so far
5. For completed phases: document fully (actions, concepts, code, errors)
6. For in-progress phases: document what's done, note what's remaining
7. For future phases: just list the phase name with "Upcoming" tag

### Subsequent runs (PROJECT_JOURNAL.md already exists)

1. Read the existing `PROJECT_JOURNAL.md` to know what's already documented
2. Read `progress.md` to see what's new since last update
3. Identify the delta — what's changed or been completed since the journal was last updated
4. **Only update the parts that need it:**
   - If a phase was completed → fill in any gaps, add error/fix details if missing
   - If new work was done in an in-progress phase → append new bullets and code
   - If a new phase started → add the new phase section
   - If the Quick-Fire answers need updating → update them
5. Add a small timestamp comment at the bottom: `<!-- Last updated: YYYY-MM-DD -->`

### When the user asks to add something specific

Sometimes the user will say "add this error we just fixed to the journal" or "document this concept." In that case, just add that specific piece to the right section. Don't re-scan or regenerate anything else.

## Writing guidelines

- **Brevity by default, depth where it matters.** A simple CRUD endpoint gets a bullet. A custom authentication flow or a tricky state management pattern gets a paragraph and maybe a code block.
- **Code blocks are selective.** Don't dump entire files. Pick the 5-15 line snippet that captures the essence. Always include a brief comment above or below explaining why it's noteworthy.
- **Errors are gold for interviews.** Interviewers love hearing about problems you solved. Document errors with enough detail that the developer can tell the story: what happened, why it was confusing, what the fix was, and what was learned.
- **Plain English.** A senior engineer or a non-technical PM should both be able to follow the journal. Avoid jargon without context — if you mention "debouncing" or "memoization," add a brief parenthetical for clarity.
- **No fluff.** Don't pad with obvious statements. "We used React because it's a popular framework" is fluff. "We chose React over vanilla JS because the UI had complex state transitions between form steps" is useful.
- **Preserve what's there.** When updating, don't rewrite existing content unless it's factually wrong. The developer may have mentally rehearsed explanations based on the current wording.

## Edge cases

- **No plan.md found:** Ask the user where their project plan is, or offer to infer phases from the codebase structure and git history (if available).
- **No progress.md found:** Same — ask or infer from git log / TODO comments / completed features.
- **Very early project (almost nothing done):** Create a skeleton journal with the tech stack and Phase 1 in progress. It'll fill in as the project progresses.
- **User asks "prep me for interviews":** Point them to the journal, and also offer to generate practice Q&A pairs based on the journal content.