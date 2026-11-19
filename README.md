# MarkX Marketplace

A multi-vendor marketplace that starts in Ethiopia: one page per product, many
verified sellers' offers under it, each with a price that shows when it was
last confirmed.

> **Status (19 November 2026): built and tested, not launched.** Sign-in, the
> catalogue, seller onboarding, seller offers with stock, the background
> worker, the cart and checkout, and the whole order life cycle after
> confirmation (dispatch, handover, completion, the direct payment record)
> are built and tested as an API. The web app in `apps/web` has the buyer's,
> the seller's and the staff's screens, and the browser journeys test it on
> GitHub. Nothing is deployed and no outside service is connected.
> See [docs/DEVELOPMENT_STATUS.md](docs/DEVELOPMENT_STATUS.md) for exactly what
> exists.

## Start here

| Read | For |
| --- | --- |
| [MARKX_MASTER_BLUEPRINT.md](MARKX_MASTER_BLUEPRINT.md) | The product: strategy, requirements, architecture, roadmap. The single source of truth |
| [docs/DEVELOPMENT_STATUS.md](docs/DEVELOPMENT_STATUS.md) | What is built, what is tested, what is not, and known problems. Next task: waiting for the founder's choice |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Engineering decisions and every departure from the blueprint |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the code is organised |
| [docs/SETUP.md](docs/SETUP.md) | How to run and test it |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | The production stack, prepared and rehearsed but **not deployed**, and every setting; procedures in [docs/runbooks/](docs/runbooks/) |
| [AGENTS.md](AGENTS.md) | Rules for AI coding agents working here |
| [docs/HANDOFF.md](docs/HANDOFF.md) | The last session's report, the decisions waiting on the founder, and the brief for the next engineering session |

## Stack

Python with FastAPI, SQLAlchemy and Alembic on PostgreSQL. The web app is
Next.js with TypeScript and Tailwind CSS (`apps/web`). The founder confirmed this stack in
the blueprint (section N).

## Rules that never bend

- MarkX never holds customers' money.
- No secrets in the repository.
- The founder's existing AWS servers and payment bot are never touched.
- Nothing is claimed to work unless it was run.
