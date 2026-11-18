# Runbooks

Procedures for running MarkX on a server (blueprint F.16, D-091). **No
server exists yet: none of these has been carried out on a real one.** Each
was rehearsed locally (`infra/production/rehearsal/rehearse.sh`) where a
rehearsal is possible, and says so.

| Runbook | When |
| --- | --- |
| [checklists.md](checklists.md) | Before and after every deployment |
| [deploy.md](deploy.md) | The first server, and every release after it |
| [migrations.md](migrations.md) | Every release that adds a migration |
| [rollback.md](rollback.md) | A release misbehaves |
| [backup-and-restore.md](backup-and-restore.md) | Daily backups, the monthly drill, and recovering the database |
| [tls-certificates.md](tls-certificates.md) | Getting and renewing the site's certificate |
| [secret-rotation.md](secret-rotation.md) | Changing a password or key |
| [telegram-linking.md](telegram-linking.md) | Connecting people's Telegram accounts: the protocol, and switching it on once the founder authorises the bot (D-093) |

Rules that hold in every runbook (AGENTS.md):

- Nothing is created, bought or deployed without the founder's written
  approval. The founder's existing AWS servers and payment bot are never
  touched.
- No secret is pasted into chat, a ticket, a commit or a screenshot.
- Never `docker compose down -v` on a server: it deletes the database.
- Migrations only go forward. A database is never "migrated down".
