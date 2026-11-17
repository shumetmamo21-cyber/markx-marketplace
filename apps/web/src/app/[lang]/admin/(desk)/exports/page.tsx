import { notFound } from "next/navigation";

import { ExportButton } from "@/components/admin/StaffActions";
import { addisDay } from "@/lib/format";
import { isLocale } from "@/lib/i18n";
import { getMe } from "@/lib/session";
import { getMessages } from "@/lib/messages";

const DAY = /^\d{4}-\d{2}-\d{2}$/;

// Exports for an accountant (blueprint C.4 "export data", D.21; D-068): four
// CSV files for whole days in Addis Ababa time. The API decides the period's
// limits and who may export; the page only picks the days.
export default async function ExportsPage({ params, searchParams }: PageProps<"/[lang]/admin/exports">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const a = t.admin;
  const me = await getMe();
  if (!me?.staff?.capabilities.includes("export_data")) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const query = await searchParams;
  const today = addisDay();
  const firstDay = typeof query.first_day === "string" && DAY.test(query.first_day) ? query.first_day : `${today.slice(0, 8)}01`;
  const lastDay = typeof query.last_day === "string" && DAY.test(query.last_day) ? query.last_day : today;
  const text = { admin: a, apiErrors: t.apiErrors };
  const kinds: [string, string][] = [
    ["fees", a.exportFees],
    ["ledger", a.exportLedger],
    ["seller-orders", a.exportSellerOrders],
    ["seller-balances", a.exportSellerBalances],
  ];
  const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.exportsTitle}</h1>
      <p className="text-slate">{a.exportsLead}</p>
      <form method="get" className="grid gap-2 sm:grid-cols-3 sm:items-end">
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.firstDay}</span><input type="date" name="first_day" defaultValue={firstDay} required className={field} /></label>
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.lastDay}</span><input type="date" name="last_day" defaultValue={lastDay} required className={field} /></label>
        <button type="submit" className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">{a.show}</button>
      </form>
      <ul className="space-y-3">
        {kinds.map(([kind, label]) => (
          <li key={kind} className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-white p-4">
            <span className="font-semibold">{label}</span>
            <ExportButton kind={kind} firstDay={firstDay} lastDay={lastDay} t={text} />
          </li>
        ))}
      </ul>
    </div>
  );
}
