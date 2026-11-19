import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime, isPast } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

// Problem cases waiting for a decision, the most urgent first (AD-09).
export default async function ProblemsPage({ params }: PageProps<"/[lang]/admin/problems">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data } = await api.GET("/api/v1/admin/orders/problems", { params: { query: { limit: 100 } } });
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{t.admin.problemsTitle}</h1>
      {(data ?? []).length === 0 ? <p className="text-slate">{t.admin.noProblems}</p> : null}
      <ul className="space-y-3">
        {(data ?? []).map((item) => {
          const late = isPast(item.decision_due_at);
          return (
            <li key={item.seller_order_id} className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-white p-4">
              <div className="space-y-1">
                <p className="font-bold">{fill(t.orders.code, { code: item.order_code })} · {item.store_slug}</p>
                <p>{t.problemType[item.problem_type as keyof typeof t.problemType] ?? item.problem_type}</p>
                <p className={late ? "text-sm font-semibold text-clay" : "text-sm text-slate"}>
                  {fill(late ? t.admin.overdue : t.admin.due, { time: formatDateTime(item.decision_due_at, lang) })}
                </p>
              </div>
              <Link href={`/${lang}/admin/orders?code=${item.order_code}`} className="inline-flex min-h-12 items-center rounded-card bg-ink px-4 font-bold text-paper">{t.admin.open}</Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
