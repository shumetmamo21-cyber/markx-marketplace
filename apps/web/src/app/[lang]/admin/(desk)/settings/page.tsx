import { notFound } from "next/navigation";

import { SettingForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

// Switches and limits (blueprint D.18 AD-06, AD-13; D-065). The API says which
// ones this person may change: the super administrator any, operations the
// risk limits. Every change is audit-logged with before and after values.
export default async function SettingsPage({ params }: PageProps<"/[lang]/admin/settings">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/settings", {});
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const shown = (value: boolean | number | string) => (typeof value === "boolean" ? (value ? a.on : a.off) : String(value));
  const rows = [...(data ?? [])].sort((x, y) => Number(y.may_change) - Number(x.may_change) || x.key.localeCompare(y.key));
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.settingsTitle}</h1>
      <p className="text-slate">{a.settingsLead}</p>
      <ul className="space-y-3">
        {rows.map((setting) => (
          <li key={setting.key} className="space-y-2 rounded-card border border-line bg-white p-4">
            <p className="font-bold"><code className="break-all">{setting.key}</code></p>
            {/* The API's own description, written in English. */}
            <p className="text-sm" lang="en">{setting.description}</p>
            <p className="text-sm text-slate">
              {fill(a.settingDefault, { value: shown(setting.default) })}
              {setting.is_overridden ? ` · ${a.settingChanged}` : ""}
            </p>
            {setting.may_change ? (
              <SettingForm settingKey={setting.key} kind={setting.kind} value={setting.value} t={text} />
            ) : (
              <p className="text-sm"><span className="font-semibold">{shown(setting.value)}</span> · {a.readOnly}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
