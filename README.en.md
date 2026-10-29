# Daydream · 白日梦

[中文](README.md) | English

**Find possibilities in everyday fragments, and say each idea briefly.**

Daydream is an Agent Skill for bold, cross-domain idea discovery. It looks for connections across your conversations, notes, reminders, everyday observations, and public discussions, then proposes new ideas to choose from: content, personal brand, consumer products, tools, services, business projects, or something outside those categories. It works with Claude Code, Codex, and other agents that support Agent Skills, and replies in your language.

It does not turn the conversation into a long interview or a role-play script by default. The default output is **an idea title, one or two sentences of description, and any useful clue it found**. Pick one, and it goes deeper on request.

## Install

### Let your agent install it

Send this to the agent you use (Claude Code, Codex, Cursor, and so on):

```text
Install this agent skill for me: https://github.com/chrzamz/daydream-skill
```

The agent reads the [For AI agents](#for-ai-agents) section below, confirms the install scope with you, and installs it.

### Install with a command

Requires Node.js **22.20+**. Install with Vercel's open-source [`skills`](https://github.com/vercel-labs/skills) CLI:

```sh
npx skills add chrzamz/daydream-skill --skill daydream
```

Install globally for Codex and Claude Code:

```sh
npx skills add chrzamz/daydream-skill --skill daydream -g -a codex claude-code
```

List the skills in this repository, list installed skills, update, or remove:

```sh
npx skills add chrzamz/daydream-skill --list
npx skills list -g
npx skills update daydream -g
npx skills remove daydream -g
```

You can also copy the whole [`skills/daydream`](skills/daydream) folder into a skills directory your agent supports. Start a new session or reload skills in your agent before using it.

## For AI agents

> This section is written for coding agents. If a user sent you this repository URL and asked you to install it, follow these steps.

This repository contains one skill, `daydream`, at [`skills/daydream/`](skills/daydream). It has no required runtime dependencies.

1. **Confirm the scope.** Unless the user already said so, ask once: install globally (all projects, `-g`) or only in the current project? Do not guess.
2. **Choose target agents.** Use your own agent id, such as `claude-code`, `codex`, `cursor`, `gemini-cli`, `opencode`, or `github-copilot`. Add other agents only if the user asks. Full list: [supported agents](https://github.com/vercel-labs/skills#supported-agents).
3. **Install with the skills CLI** (Node.js 22.20+):

   ```sh
   # current project
   npx skills add chrzamz/daydream-skill --skill daydream -a <agent-id> -y

   # global
   npx skills add chrzamz/daydream-skill --skill daydream -a <agent-id> -g -y
   ```

   `-a` accepts several ids, for example `-a claude-code codex`. Do not use `--all`.

4. **Without Node.js**, copy the folder instead:

   ```sh
   git clone --depth 1 https://github.com/chrzamz/daydream-skill /tmp/daydream-skill
   cp -R /tmp/daydream-skill/skills/daydream <skills-dir>/daydream
   ```

   `<skills-dir>` is your agent's skills directory, for example `.claude/skills` (project) or `~/.claude/skills` (global) for Claude Code, and `.agents/skills` or `~/.agents/skills` for Codex.

5. **Verify.** Run `npx skills list` (add `-g` for global) and confirm `daydream` is listed, or check that `<skills-dir>/daydream/SKILL.md` exists.
6. **Tell the user how to start.** They may need a new session or a skills reload. Then try `/daydream` in Claude Code, `$daydream` in Codex, or simply ask for new ideas.

Installation only places the skill files. Do not run the bundled Python scripts, read the user's notes or chat history, create scheduled tasks, or ask for accounts or API keys as part of installing.

## Usage

```text
Use $daydream to find a few new ideas in my recent chats and notes. Be bold, and keep each one short.

Use Daydream to see what this half-formed thought could grow into, and look for outside signals on Hacker News and Product Hunt.

Pull three distinctive article or social post angles from this material, with titles and the hook for each.

The second idea is interesting. Find real usage situations, then turn it into something I can test on a small scale.
```

Use `/daydream` in Claude Code or `$daydream` in Codex, or let the agent pick it up from the description.

## How it works

1. Starts from existing material or public signals, and separates the user's ideas from AI suggestions, existing projects, and later decisions.
2. Makes cross-domain leaps: new audiences, situations, formats, and unexpected combinations.
3. Does a moderate amount of public research while an idea is young: real complaints, workarounds, existing products, and disagreement.
4. Proposes candidates briefly. An existing competitor does not disqualify an idea; likes are not willingness to pay; no search results means unknown.
5. Goes deeper only after you pick one, and respects ideas you cancelled, finished, or put on hold.

Personal records are one starting point, not the limit of imagination. A thought that appeared only once is still worth exploring. See the [examples](skills/daydream/references/examples.md) for output style.

## Data sources and boundaries

The core skill needs no Python and no particular account. It works with the current conversation, material you provide, and whatever search tools the host agent already has.

The optional collectors use the Python **3.9+ standard library**:

- `collect_signals.py` reads explicitly specified Claude Code and Codex JSONL, Markdown, and generic JSON/JSONL exports.
- `collect_apple.py` reads a specified Notes folder or Reminders list on macOS through the apps' own interface, read-only, with existing system permission.

Neither collector makes network requests or modifies its sources. Both skip records that look like common credentials, but they **do not guarantee complete removal of private information**; choose folders and lists accordingly. Whether the model runs locally depends on your agent, so local collectors alone do not make the whole process offline.

For OpenCode, Gemini, or other sources, use the host's connectors or a generic export; this version has no built-in parser for their private databases. See [sources and commands](skills/daydream/references/sources.md).

Hacker News, Product Hunt, and social media research use the host's available connectors, CLIs, or web search. The skill does not promise platform access and does not bypass logins or permissions.

Installing starts no background process or scheduled task. For periodic runs, set up a schedule explicitly in an agent that supports it, read incrementally, and notify only about meaningful new findings.

## Publishing on skills.sh

The skill files are hosted on GitHub. According to the [skills.sh FAQ](https://skills.sh/docs/faq), once people install with `npx skills add owner/repo`, the platform discovers and counts the skill through anonymous install telemetry. There is no website to deploy and no separate upload step.

A public, installable repository is not necessarily searchable or reviewed on the leaderboard right away; listing and audits can lag. Do not create repeated installs to boost rankings.

## Development

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use synthetic data and cover collection, noise filtering, deduplication, date filtering, and credential skipping. Behavioral scenarios are in [evals/scenarios.md](evals/scenarios.md); automated tests do not prove idea quality or market demand.

This repository contains no real conversations, notes, customer information, or personal paths. Keep private working data outside the repository.

## License

[MIT](LICENSE)
