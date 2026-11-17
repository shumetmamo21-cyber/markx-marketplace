import { BottomNav } from "@/components/BottomNav";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { notFound } from "next/navigation";

export default async function ShopLayout({ children, params }: LayoutProps<"/[lang]">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  return (
    <>
      <SiteHeader lang={lang} t={t} />
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        {children}
      </main>
      <SiteFooter t={t} />
      <BottomNav lang={lang} t={t} />
    </>
  );
}
