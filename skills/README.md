# Skills

Agent skills for working on the Offensive Summit 2026 badge. Each subfolder holds
a `SKILL.md` with YAML frontmatter (`name`, `description`) plus any supporting
files — the convention used by Claude Code and other agent tooling that loads
skills from disk.

| Skill | Use for |
|---|---|
| [`badge-app-development`](badge-app-development/SKILL.md) | Writing, debugging, and deploying badge apps |

Point your agent at this folder (or symlink a skill into your agent's skills
directory) and it will pick up the badge conventions, API gotchas, and hardware
constraints without re-reading all of `docs/`.
