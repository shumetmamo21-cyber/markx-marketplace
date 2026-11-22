import { BottomNav } from "@/components/BottomNav";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { isLocale } from "@/lib/i18n";
import { isLite } from "@/lib/lite-server";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";
import { notFound } from "next/navigation";

export default async function ShopLayout({ children, params }: LayoutProps<"/[lang]">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const [t, me, lite] = await Promise.all([getMessages(lang), getMe(), isLite()]);
  return (
    <>
      <SiteHeader lang={lang} t={t} signedIn={me !== null} />
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        {children}
      </main>
      <SiteFooter t={t} lang={lang} lite={lite} />
      <BottomNav lang={lang} t={t} />
    </>
  );
}
