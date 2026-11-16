import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { defineConfig } from 'prisma/config';

/**
 * Prisma 7 no longer loads .env automatically. Walk up from the working
 * directory to find the repo-root .env so `pnpm db:*` works from anywhere.
 */
function loadNearestEnvFile(): void {
  let dir = process.cwd();
  for (let depth = 0; depth < 5; depth += 1) {
    const candidate = resolve(dir, '.env');
    if (existsSync(candidate)) {
      process.loadEnvFile(candidate);
      return;
    }
    const parent = dirname(dir);
    if (parent === dir) return;
    dir = parent;
  }
}

loadNearestEnvFile();

const databaseUrl = process.env.DATABASE_URL;

export default defineConfig({
  schema: 'prisma/schema.prisma',
  // Commands that need a connection (migrate, studio) fail with a clear
  // message if DATABASE_URL is absent; `generate` does not need one.
  datasource: {
    ...(databaseUrl ? { url: databaseUrl } : {}),
  },
});
