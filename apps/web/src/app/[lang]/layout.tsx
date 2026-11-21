import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";

import "../globals.css";
import { ResilienceProvider } from "@/components/Resilience";
import { resilienceText } from "@/lib/fallback-text";
import { LOCALES, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const dynamicParams = false;

export function generateStaticParams() {
  return LOCALES.map((lang) => ({ lang }));
}

export async function generateMetadata({ params }: LayoutProps<"/[lang]">): Promise<Metadata> {
  const { lang } = await params;
  if (!isLocale(lang)) return {};
  const t = await getMessages(lang);
  return {
    title: { default: t.meta.title, template: `%s · ${t.brand.wordmark}` },
    description: t.meta.description,
    alternates: { languages: { am: "/am", en: "/en" } },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0e1b2a",
};

export default async function RootLayout({ children, params }: LayoutProps<"/[lang]">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  return (
    <html lang={lang}>
      <body className="min-h-dvh bg-paper text-ink antialiased">
        {/* The words for a failed call and the error pages (D-100). */}
        <ResilienceProvider text={resilienceText(lang, t)}>{children}</ResilienceProvider>
      </body>
    </html>
  );
}
