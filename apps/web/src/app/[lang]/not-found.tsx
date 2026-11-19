import Link from "next/link";

// Rendered without the language at hand: both languages, briefly.
export default function NotFound() {
  return (
    <main id="main" className="mx-auto max-w-xl space-y-4 px-4 py-16 text-center">
      <p className="text-5xl font-extrabold">404</p>
      <p lang="en">We could not find that page.</p>
      <p lang="am">ያንን ገጽ ማግኘት አልቻልንም።</p>
      <p>
        <Link href="/" className="font-semibold underline">MarkX</Link>
      </p>
    </main>
  );
}
