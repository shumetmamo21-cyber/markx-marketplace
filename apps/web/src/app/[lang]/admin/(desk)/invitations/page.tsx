import { notFound } from "next/navigation";

import { InviteForm, RevokeInvitationForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, isPast } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

// Onboarding is invitation-only at launch (blueprint D.3, D-019): staff invite
// a phone number; the person who owns it may open one application.
export default async function InvitationsPage({ params }: PageProps<"/[lang]/admin/invitations">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/sellers/invitations", { params: { query: { limit: 200 } } });
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const rows = data ?? [];
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">{a.invitationsTitle}</h1>
      <InviteForm t={text} />
      {rows.length === 0 ? <p className="text-slate">{a.noInvitations}</p> : null}
      <ul className="divide-y divide-line rounded-card border border-line bg-white">
        {rows.map((row) => {
          const open = !row.used_at && !row.revoked_at && !isPast(row.expires_at);
          const state = row.used_at
            ? fill(a.used, { time: formatDateTime(row.used_at, lang) })
            : row.revoked_at
              ? fill(a.revoked, { time: formatDateTime(row.revoked_at, lang) })
              : fill(a.expires, { time: formatDateTime(row.expires_at, lang) });
          return (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
              <div>
                <p className="font-semibold">{row.phone}</p>
                <p className="text-sm text-slate">{state}{row.note ? ` · ${row.note}` : ""}</p>
              </div>
              {open ? <RevokeInvitationForm id={row.id} t={text} /> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
