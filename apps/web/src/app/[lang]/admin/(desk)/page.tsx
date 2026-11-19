import { notFound, redirect } from "next/navigation";

import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

import { adminMenu } from "./menu";

// Queues first (blueprint I.4): the first queue this role may open. Catalogue
// and finance staff hold no problem cases, so they must not be sent there.
export default async function AdminHome({ params }: PageProps<"/[lang]/admin">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me || me.session_kind !== "staff" || !me.staff) redirect(`/${lang}/admin/sign-in`);
  const t = await getMessages(lang);
  const first = adminMenu(lang, me.staff.capabilities, t)[0];
  if (first) redirect(first.href);
  return <p className="text-slate">{t.admin.noAccess}</p>;
}
