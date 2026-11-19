import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

// Operations (D-064): the marketplace's own checks. Open alerts, the
// scheduled jobs and the outbox, as the API reports them; nothing here acts.
export default async function OpsPage({ params }: PageProps<"/[lang]/admin/ops">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [status, recent] = await Promise.all([
    api.GET("/api/v1/admin/ops/status", {}),
    api.GET("/api/v1/admin/ops/alerts", { params: { query: { limit: 20 } } }),
  ]);
  const a = t.admin;
  if (status.response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  if (!status.data) return <p role="alert" className="font-semibold text-clay">{t.apiErrors.unknown}</p>;
  const { open_alerts: open, jobs, outbox } = status.data;
  const resolved = (recent.data ?? []).filter((alert) => alert.resolved_at);
  const when = (iso: string) => formatDateTime(iso, lang);
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">{a.opsTitle}</h1>
      <section className="space-y-2">
        <h2 className="text-lg font-bold">{a.openAlerts}</h2>
        {open.length === 0 ? <p className="text-slate">{a.noAlerts}</p> : null}
        <ul className="space-y-2">
          {open.map((alert) => (
            <li key={alert.id} className="space-y-1 rounded-card border border-clay bg-white p-4">
              <p className="font-bold">{codeLabel(t, "alertSeverity", alert.severity)} · {alert.summary}</p>
              <p className="text-sm text-slate">{alert.source} · {fill(a.alertSeen, { first: when(alert.first_seen_at), last: when(alert.last_seen_at), count: alert.occurrences })}</p>
            </li>
          ))}
        </ul>
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-bold">{a.jobsTitle}</h2>
        <ul className="divide-y divide-line rounded-card border border-line bg-white">
          {jobs.map((job) => (
            <li key={job.name} className="space-y-1 p-3 text-sm">
              <p className="font-semibold">{job.name}</p>
              <p className="text-slate">
                {fill(a.jobNext, { time: when(job.next_run_at) })} · {job.last_succeeded_at ? fill(a.jobLastOk, { time: when(job.last_succeeded_at) }) : a.jobNever}
              </p>
              {job.consecutive_failures > 0 ? <p className="font-semibold text-clay">{fill(a.jobFailures, { count: job.consecutive_failures })}{job.last_error ? ` · ${fill(a.jobError, { error: job.last_error })}` : ""}</p> : null}
            </li>
          ))}
        </ul>
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-bold">{a.outboxTitle}</h2>
        {outbox.length === 0 ? <p className="text-slate">{a.noOutbox}</p> : null}
        <ul className="divide-y divide-line rounded-card border border-line bg-white">
          {outbox.map((row) => (
            <li key={`${row.topic}-${row.status}`} className="flex justify-between gap-2 p-3 text-sm"><span>{row.topic} · {codeLabel(t, "outboxStatus", row.status)}</span><span className="font-semibold">{row.count}</span></li>
          ))}
        </ul>
      </section>
      {resolved.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-lg font-bold">{a.recentAlerts}</h2>
          <ul className="divide-y divide-line rounded-card border border-line bg-white">
            {resolved.map((alert) => (
              <li key={alert.id} className="p-3 text-sm">{codeLabel(t, "alertSeverity", alert.severity)} · {alert.summary} · {fill(a.resolvedAt, { time: when(alert.resolved_at ?? alert.last_seen_at) })}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
