import type { Locale, Messages } from "@/lib/i18n";

// The lite-mode switch (C-12; D-107) is a plain link drawn here on the
// server: no script. The switch route goes back to the page it came from.
export function SiteFooter({ t, lang, lite = false }: { t: Messages; lang?: Locale; lite?: boolean }) {
  return (
    <footer className="mt-12 bg-ink pb-20 text-paper md:pb-0">
      <div className="tibeb" aria-hidden="true" />
      <div className="mx-auto max-w-6xl space-y-2 px-4 py-8 text-sm">
        <p className="font-bold">{t.brand.wordmark}</p>
        <p className="max-w-prose opacity-90">{t.footer.about}</p>
        {lang ? (
          <p>
            {lite ? <span className="mr-3 font-semibold">{t.lite.state}</span> : null}
            <a href={`/${lang}/lite?on=${lite ? "0" : "1"}`} rel="nofollow" className="inline-flex min-h-12 items-center underline">{lite ? t.lite.off : t.lite.on}</a>
          </p>
        ) : null}
        {process.env.NODE_ENV !== "production" ? <p className="opacity-70">{t.footer.demo}</p> : null}
      </div>
    </footer>
  );
}
