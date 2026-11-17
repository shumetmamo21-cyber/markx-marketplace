import type { Locale, Messages } from "@/lib/i18n";

import { SearchBox } from "./SearchBox";

// A plain form: search works before any script loads (blueprint F.1); the
// box adds suggestions once it does.
export function SearchForm({ lang, t, query = "" }: { lang: Locale; t: Messages; query?: string }) {
  return (
    <form action={`/${lang}/search`} method="get" role="search" className="flex w-full gap-2">
      <SearchBox lang={lang} query={query} labels={{ label: t.search.label, placeholder: t.search.placeholder, suggestions: t.search.suggestions }} />
      <button
        type="submit"
        className="min-h-12 shrink-0 rounded-card bg-adey px-4 font-bold text-ink hover:brightness-95"
      >
        {t.search.submit}
      </button>
    </form>
  );
}
