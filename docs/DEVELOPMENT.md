# Development

## Prerequisites

- Node 22+ (`.nvmrc` pins the major; `nvm use` picks it up)
- pnpm 10+ (`corepack enable pnpm`)
- Docker, for the local Postgres instance

## First run

```bash
pnpm install
cp .env.example .env
```

Start the database and apply the schema:

```bash
docker compose up -d
pnpm db:generate
pnpm db:migrate
```

Then `pnpm dev` and open http://localhost:3000.

## Environment variables

`.env` is git-ignored. `.env.example` is the checked-in template — when you
add a variable, add it there too, with a placeholder and never a real secret.

| Variable              | Purpose                                |
| --------------------- | -------------------------------------- |
| `DATABASE_URL`        | Postgres connection string             |
| `NEXT_PUBLIC_APP_URL` | Public base URL of the storefront      |
| `AUTH_SECRET`         | Session signing key (not yet wired up) |

## Changing the data model

1. Edit `packages/db/prisma/schema.prisma`.
2. Run `pnpm db:migrate` — Prisma writes a migration and regenerates the client.
3. Commit the generated migration directory alongside the schema change.

The generated client (`packages/db/generated/`) is git-ignored and rebuilt by
`pnpm db:generate`. CI runs that step before typechecking.

## Before pushing

```bash
pnpm format && pnpm lint && pnpm typecheck && pnpm build
```

CI runs the same sequence.
