import type { Messages } from "@/lib/i18n";

export function SiteFooter({ t }: { t: Messages }) {
  return (
    <footer className="mt-12 bg-ink pb-20 text-paper md:pb-0">
      <div className="tibeb" aria-hidden="true" />
      <div className="mx-auto max-w-6xl space-y-2 px-4 py-8 text-sm">
        <p className="font-bold">{t.brand.wordmark}</p>
        <p className="max-w-prose opacity-90">{t.footer.about}</p>
        {process.env.NODE_ENV !== "production" ? <p className="opacity-70">{t.footer.demo}</p> : null}
      </div>
    </footer>
  );
}
