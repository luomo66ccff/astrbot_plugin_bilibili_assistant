# Changelog

## v0.2.13 - 2026-06-14

Initial public release prepared for GitHub.

### Added

- AstrBot commands for enabling, disabling, and checking plugin status.
- B站 video lookup and comment reading with main-comment/reply distinction.
- AI reply generation from raw text or a target comment `rpid`.
- Reply draft workflow with edit, reject, send, confirmation, and dry-run safeguards.
- Comment monitoring tasks with notify-only, draft, and auto-reply modes.
- Dashboard page for status, QR login, pending drafts, monitor tasks, and logs.
- QR login support for automatically saving B站 Cookie through AstrBot config.
- Safety checks for blocked keywords, duplicate replies, blacklists, and reply frequency.
- SQLite audit logging and CSV export.
- Unit tests for core parsing, storage, safety, rules, loading, QR PNG generation, and AI fallback behavior.

### Notes

- The project was developed with AI assistance.
- The default configuration keeps `dry_run=true`, `auto_reply_enabled=false`, and `require_confirmation=true`.
- B站 web endpoints may change or trigger risk controls; production deployments should keep conservative request frequency and manual review enabled.
