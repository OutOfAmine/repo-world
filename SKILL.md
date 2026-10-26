---
name: repo-world
description: Turn any codebase into a playable pixel-art RPG city where folders are districts, classes are NPCs you can talk to, god classes are bosses, circular imports are rifts, and deleted files rest in a graveyard. Use when the user wants to explore, visualize, gamify or onboard onto a repo ("turn my repo into a game", "repo world", "make onboarding fun", "show my codebase as a city", /repo-world).
---

# Repo World

Turns a repository into a single self-contained HTML game. Deterministic scan first, then Claude writes the lore, then a build step bakes both into the game.

```
repo ──scan.py──▶ world.json ──(Claude writes lore.json)──▶ build.py ──▶ repo-world.html
```

| In the code | In the world |
|---|---|
| Top-level folder / module | Fenced district with a sign |
| File | House (roof color = role: controller, model, service…) |
| Main class / component | NPC standing at the door, talks about itself |
| File ≥ 450 LOC or ≥ 30 methods | Dark tower + **boss** monster |
| Top ~6% most-edited files (git) | House on fire 🔥 |
| Imports between districts | Roads on the world map |
| Import cycle (SCC) | Portal in **The Rift** |
| File deleted in git history | Tombstone in **The Graveyard** (author, date, commit msg) |
| Top contributors | Statues in the **Hall of Heroes** (founder in gold) |

## Workflow

### 1. Scan (deterministic, no LLM)

```bash
python3 <skill>/scripts/scan.py <repo> -o world.json
```

Options: `--max-files 600` (keeps the largest files beyond that), `--max-bytes 400000`.
Supports PHP/Laravel, TS/JS (Angular, React, Vue, Svelte, Next, Nest), Python, Go, Java/Kotlin/C#, Ruby. Git data is optional: without `.git` there is no graveyard, heroes or fire.

Read the one-line summary it prints. If it says `0 imports` on a JS/TS repo, check for an unusual path alias; the game still works, the map just has no roads.

### 2. Write the lore (this is the part that makes it viral)

Read `world.json`, then actually **open the important files** before writing anything. Never invent behavior: every NPC line must be true of the code. Pick:

- **8–20 NPCs**: highest `in` (most imported), every boss, the main controller/route entry points, the most `churn`, and 1–2 surprising ones (orphans with `in: 0`, files with many TODOs).
- **4–8 quests** that teach the codebase: "follow a request from route to DB", "find who sends the welcome email", "find where payments are validated". Each `target` must be a real `path` from `world.json`, or one of `kind:tomb`, `kind:portal`, `hero:0`, `role:<role>`, `district:<district name>`.
- **District names + one-line lore** keyed by the district's original `name`.

Write `lore.json`:

```json
{
  "title": "The Kingdom of Acme",
  "tagline": "One line shown on the title screen.",
  "districts": { "Http/Controllers": { "name": "Gatekeepers' Quarter", "lore": "Every request knocks here first." } },
  "npcs": {
    "app/Models/User.php": {
      "title": "The Elder",
      "lines": ["I am <code>User</code>. 119 files import me.", "Ask <code>UserPolicy</code> what each rank may do."]
    }
  },
  "quests": [
    { "title": "The Elder", "text": "Find the citizen everyone imports.", "target": "app/Models/User.php", "hint": "The Archives", "xp": 100 }
  ],
  "graveyardName": "optional", "heroesName": "optional", "riftName": "optional"
}
```

Writing rules:
- First person, 2–5 short lines per NPC, max ~160 chars per line. Wrap identifiers in `<code>`. Only `<code>` is allowed as markup.
- Personality comes from facts: size, churn, how many import it, odd naming, TODOs, what it really does. Funny is good, wrong is not.
- Bosses: menacing, and say concretely why they are dangerous (what breaks if you touch them).
- Write in the user's language when they wrote in one (Darija, French…); keep code identifiers as-is.
- Never put secrets, tokens, emails or `.env` values in lore.

See `examples/laravel.io.lore.json` for a full example.

Skip this step only if the user wants a quick result: the game auto-generates dialogue and quests from the scan.

### 3. Build

```bash
python3 <skill>/scripts/build.py world.json -l lore.json -o repo-world.html
```

It warns about lore entries that point to unknown files or districts. Fix them and rebuild.

### 4. Deliver

The output is one HTML file (~100–400 KB, no build step, works offline except the pixel font). Publish it as an artifact or send the file. Tell the user in one or two lines: districts count, boss count, the first quest. Suggest they post a GIF of the map.

## Controls

WASD / arrows move · E / Space / tap A to talk · Q quest log · M world map (click anywhere to fast-travel) · Esc close. Click an NPC to jump to it and talk, click the ground to teleport. Mouse wheel / +- / pinch to zoom. Touch D-pad appears on phones. Progress and position save in localStorage per repo.

## Large repos

For monorepos, scan one package at a time (`scan.py packages/api`) or raise `--max-files`. Above ~1,500 files the world gets big; districts are capped at 16 (smaller ones merge into "Outskirts").
