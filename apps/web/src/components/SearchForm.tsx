import type { Locale, Messages } from "@/lib/i18n";

// A plain form: search works before any script loads (blueprint F.1).
export function SearchForm({ lang, t, query = "" }: { lang: Locale; t: Messages; query?: string }) {
  return (
    <form action={`/${lang}/search`} method="get" role="search" className="flex w-full gap-2">
      <label htmlFor="q" className="sr-only">
        {t.search.label}
      </label>
      <input
        id="q"
        name="q"
        type="search"
        defaultValue={query}
        placeholder={t.search.placeholder}
        autoComplete="off"
        enterKeyHint="search"
        className="min-h-12 w-full min-w-0 rounded-card border border-line bg-white px-4 text-base placeholder:text-slate"
      />
      <button
        type="submit"
        className="min-h-12 shrink-0 rounded-card bg-adey px-4 font-bold text-ink hover:brightness-95"
      >
        {t.search.submit}
      </button>
    </form>
  );
}
