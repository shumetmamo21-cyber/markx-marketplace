# MarkX Marketplace

A multi-vendor e-commerce marketplace.

> **Status: scaffold.** The structure, tooling and data model are in place.
> There is no business logic, authentication or payment integration yet.

## Stack

| Layer      | Choice                                  |
| ---------- | --------------------------------------- |
| Language   | TypeScript (strict)                     |
| Storefront | Next.js (App Router) + React + Tailwind |
| Database   | PostgreSQL via Prisma                   |
| Monorepo   | pnpm workspaces                         |
| CI         | GitHub Actions                          |

## Layout

```
apps/
  web/              Next.js storefront
packages/
  db/               Prisma schema + client singleton
  shared/           Money helpers, Zod schemas, shared types
docs/
  DEVELOPMENT.md    Local setup
  ARCHITECTURE.md   Data model and conventions
```

## Quick start

Requires Node 22+, pnpm 10+, and Docker (for local Postgres).

```bash
pnpm install
cp .env.example .env
docker compose up -d          # start Postgres
pnpm db:generate              # generate the Prisma client
pnpm db:migrate               # create the schema
pnpm dev                      # http://localhost:3000
```

## Commands

| Command           | Does                           |
| ----------------- | ------------------------------ |
| `pnpm dev`        | Run the storefront in dev mode |
| `pnpm build`      | Build every workspace package  |
| `pnpm lint`       | ESLint across the repo         |
| `pnpm typecheck`  | TypeScript, no emit            |
| `pnpm format`     | Prettier, write                |
| `pnpm db:migrate` | Create/apply a dev migration   |
| `pnpm db:studio`  | Browse the database            |

## Conventions

**Money is never a float.** Amounts are integers in minor units (cents,
santim) paired with an ISO-4217 currency code. Use the helpers in
`@markx/shared` rather than doing arithmetic inline. See
`packages/shared/src/money.ts`.

## License

MIT — see [LICENSE](./LICENSE).
