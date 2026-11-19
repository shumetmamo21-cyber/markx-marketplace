import { notFound } from "next/navigation";

import { CreateStaffForm, StaffActiveForm, StaffRoleForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, isPast } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

// Staff accounts (blueprint D.18 AD-06, C.4; D-065): the super administrator
// creates accounts, changes roles and switches people off. The API refuses
// changing your own role or switching yourself off, and never lets MarkX lose
// its last super administrator; this page shows those refusals in words.
export default async function StaffPage({ params }: PageProps<"/[lang]/admin/staff">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/staff", {});
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const roles = t.labels.staffRole;
  const rows = data ?? [];
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">{a.staffTitle}</h1>
      <section className="space-y-2">
        <h2 className="text-lg font-bold">{a.addStaff}</h2>
        <CreateStaffForm t={text} roleLabels={roles} />
      </section>
      <p className="text-sm text-slate">{a.sessionsEnd}</p>
      <ul className="space-y-3">
        {rows.map((member) => (
          <li key={member.id} className="space-y-3 rounded-card border border-line bg-white p-4">
            <div>
              <p className="font-bold">{member.name ?? "—"} <span className="font-normal text-slate">· {fill(a.phoneEnds, { last4: member.phone_last4 })}</span></p>
              <p className="text-sm text-slate">
                {codeLabel(t, "staffRole", member.role)} · {member.is_active ? a.active : a.inactive}
                {member.locked_until && !isPast(member.locked_until) ? ` · ${fill(a.lockedUntil, { time: formatDateTime(member.locked_until, lang) })}` : ""}
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <StaffRoleForm staffId={member.id} role={member.role} t={text} roleLabels={roles} />
              <StaffActiveForm staffId={member.id} active={member.is_active} t={text} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
