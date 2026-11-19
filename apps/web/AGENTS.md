# The MarkX web app

Read the repository's root `AGENTS.md` first; its rules apply here in full.

Next.js 16 differs from older versions in ways your training may not know:
`middleware` is now `proxy.ts`, route `params` and `searchParams` are promises,
Turbopack is the default bundler, and `next lint` is gone (run `npm run lint`).
Read the guide for the feature you touch in `node_modules/next/dist/docs/`
before writing code.

House rules for this app (docs/DECISIONS.md, D-055):

- **No business rule lives here.** Prices, totals, permissions and statuses
  come from the API. The app shows them and sends the person's choices.
- **Every API read is `no-store`.** A price is never served from a cache.
- **Server pages read the API with the visitor's cookies** (`src/lib/api/server.ts`);
  **browser actions call `/api/v1` on the same origin** (`src/lib/api/browser.ts`),
  which adds the `X-MarkX-Client` and CSRF headers the API requires.
- **No customer-facing text in code.** It lives in `messages/am.json` and
  `messages/en.json`, with the same keys in both.
- **Types come from the API.** After an API change run, from `apps/api`,
  `uv run python -m scripts.export_openapi ../web/src/lib/api/openapi.json`,
  then `npm run gen:api` here. CI fails if they are stale.

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
