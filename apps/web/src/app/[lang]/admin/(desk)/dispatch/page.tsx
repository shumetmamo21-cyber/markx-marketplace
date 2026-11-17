import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel, statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

// The dispatch board (blueprint D.18, AD-05) over D-065's route: parts waiting
// to leave a shop by rider or courier, oldest first, late ones marked by the
// API. Dispatching itself happens in the orders desk, behind the same
// capability.
export default async function DispatchPage({ params }: PageProps<"/[lang]/admin/dispatch">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/dispatch-board", { params: { query: { limit: 200 } } });
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const rows = data ?? [];
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.dispatchTitle}</h1>
      {rows.length === 0 ? <p className="text-slate">{a.noDispatch}</p> : null}
      <ul className="space-y-3">
        {rows.map((row) => (
          <li key={row.seller_order_id} className="space-y-1 rounded-card border border-line bg-white p-4">
            <p className="font-bold">
              {row.order_code} <span className="font-normal text-slate">· {row.store_slug} · {row.zone_code}</span>
              {row.late ? <span className="ml-2 rounded-full bg-clay px-2 py-0.5 text-sm font-semibold text-paper">{a.late}</span> : null}
            </p>
            <p className="text-sm text-slate">
              {statusLabel(t, row.status)} · {codeLabel(t, "deliveryMode", row.mode)} · {fill(a.waitingSince, { time: formatDateTime(row.waiting_since, lang) })}
              {row.promised_by ? ` · ${fill(a.promisedBy, { time: formatDateTime(row.promised_by, lang) })}` : ""}
            </p>
            <Link href={`/${lang}/admin/orders?code=${encodeURIComponent(row.order_code)}`} className="inline-block min-h-12 py-3 font-semibold underline">{a.openOrder}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
