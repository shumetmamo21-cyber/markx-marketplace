import { PrismaPg } from '@prisma/adapter-pg';
import { PrismaClient } from '../generated/client/index.js';

export * from '../generated/client/index.js';

/**
 * Next.js re-evaluates modules on hot reload, which would open a fresh
 * connection pool each time until Postgres refuses new clients. Cache the
 * instance on globalThis in development so reloads reuse one pool.
 */
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

let cached: PrismaClient | undefined;

/**
 * Lazily construct the client. Deliberately not a top-level singleton:
 * `next build` evaluates modules without a database, so importing this
 * module must never throw.
 */
export function getPrisma(): PrismaClient {
  if (cached) return cached;

  if (globalForPrisma.prisma) {
    cached = globalForPrisma.prisma;
    return cached;
  }

  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error(
      'DATABASE_URL is not set. Copy .env.example to .env and fill it in (see docs/DEVELOPMENT.md).',
    );
  }

  const client = new PrismaClient({ adapter: new PrismaPg(connectionString) });
  cached = client;
  if (process.env.NODE_ENV !== 'production') {
    globalForPrisma.prisma = client;
  }
  return client;
}
