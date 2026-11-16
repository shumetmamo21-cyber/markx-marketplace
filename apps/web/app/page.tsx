import { formatMoney, money } from '@markx/shared';

/**
 * Placeholder data. Replace with a query against @markx/db once a database
 * is provisioned — see docs/DEVELOPMENT.md.
 */
const sampleProducts = [
  { id: '1', title: 'Hand-woven Habesha Kemis', priceMinor: 450_000, seller: 'Addis Textiles' },
  {
    id: '2',
    title: 'Single-origin Yirgacheffe, 1kg',
    priceMinor: 85_000,
    seller: 'Sidama Roasters',
  },
  { id: '3', title: 'Leather Messenger Bag', priceMinor: 320_000, seller: 'Merkato Leather' },
] as const;

export default function HomePage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-16">
      <header className="mb-12">
        <h1 className="text-4xl font-semibold tracking-tight">MarkX</h1>
        <p className="mt-2 text-lg opacity-70">
          A multi-vendor marketplace. Scaffold only — no business logic yet.
        </p>
      </header>

      <section aria-labelledby="featured">
        <h2 id="featured" className="mb-4 text-sm font-medium uppercase tracking-wide opacity-60">
          Featured
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sampleProducts.map((product) => (
            <li
              key={product.id}
              className="rounded-lg border border-black/10 p-4 dark:border-white/15"
            >
              <h3 className="font-medium">{product.title}</h3>
              <p className="mt-1 text-sm opacity-60">{product.seller}</p>
              <p className="mt-3 font-mono text-sm">
                {formatMoney(money(product.priceMinor, 'ETB'))}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
