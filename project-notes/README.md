# Project Notes

This directory is a curated, **one-way mirror** of the maintainer's internal project knowledge. The source of truth is a private Obsidian vault.

## What's here

- **Roadmap.md** — current phase, active work, completed tracks at a glance
- **Architecture.md / Architecture Decisions.md** — system design + the *why* behind load-bearing choices
- **How Discovery Works.md** — tool/capability discovery pipeline reference
- **Track - \*.md** — multi-session work streams with phase status, invariants, and decisions
- **Test Audit - \*.md** — coverage analysis and quality reviews
- **Integration Depth Playbook.md / Widget Authoring.md** — design playbooks for contributors
- **Completed Tracks.md** — compressed history of shipped tracks
- **E2E Testing Roadmap.md** — end-to-end test coverage plan
- **Plan - \*.md** — drafted architectural plans (read-only proposals)

## What's NOT here

Open bugs, raw scratch notes, session logs, internal fix history, and operational runbooks (server IPs, credentials, etc.) stay in the vault. If a feature seems undocumented here, it likely is.

## Contributing

These files are mirrored from the vault — direct edits to files in this directory will be **overwritten** on the next sync. To propose a change:

- **Typo / clarification** — open a PR against the specific file. The maintainer will hand-merge into the vault.
- **Substantive change** — open an issue describing the proposed update. Discussion happens in the issue; the maintainer applies in the vault and the change appears here on the next mirror.

## Freshness caveat

The mirror is **best-effort, not real-time.** It's driven by a Claude Code hook that fires on edit, plus a periodic bulk reconcile. Files may lag the live vault by a session or two, especially after archive/rename operations. Treat the timestamps in each file's frontmatter as authoritative for "last meaningful update."

## License

These notes are part of the Spindrel project and licensed under [AGPL-3.0](../LICENSE).
