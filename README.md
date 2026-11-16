# MarkX Marketplace

A multi-vendor marketplace that starts in Ethiopia: one page per product, many
verified sellers' offers under it, each with a price that shows when it was
last confirmed.

> **Status: early foundation.** The back-end foundation is built and tested.
> No marketplace feature works yet and there is no web app. Nothing is deployed.
> See [docs/DEVELOPMENT_STATUS.md](docs/DEVELOPMENT_STATUS.md) for exactly what
> exists.

## Start here

| Read | For |
| --- | --- |
| [MARKX_MASTER_BLUEPRINT.md](MARKX_MASTER_BLUEPRINT.md) | The product: strategy, requirements, architecture, roadmap. The single source of truth |
| [docs/DEVELOPMENT_STATUS.md](docs/DEVELOPMENT_STATUS.md) | What is built, what is tested, what is not, and the next task |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Engineering decisions and every departure from the blueprint |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the code is organised |
| [docs/SETUP.md](docs/SETUP.md) | How to run and test it |
| [AGENTS.md](AGENTS.md) | Rules for AI coding agents working here |

## Stack

Python with FastAPI, SQLAlchemy and Alembic on PostgreSQL. The web app will be
Next.js with TypeScript and Tailwind CSS. The founder confirmed this stack in
the blueprint (section N).

## Rules that never bend

- MarkX never holds customers' money.
- No secrets in the repository.
- The founder's existing AWS servers and payment bot are never touched.
- Nothing is claimed to work unless it was run.
