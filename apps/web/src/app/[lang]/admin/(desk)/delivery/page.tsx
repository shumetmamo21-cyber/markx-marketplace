import { notFound } from "next/navigation";

import { AreaSwitch, NewAreaForm, NewZoneForm, RateForm, ZoneForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

const METHODS = ["seller_rider", "partner_courier"] as const;

// Delivery zones (blueprint D.13, AD-05): the zones buyers choose from, the
// areas inside each, and each zone's fee and promised time per way of
// delivering. Staff who may change delivery and risk settings only.
export default async function DeliveryPage({ params }: PageProps<"/[lang]/admin/delivery">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/delivery/zones", {});
  const a = t.admin;
  if (response.status === 403) return <p role="alert">{a.notAllowed}</p>;
  const zones = data ?? [];
  const text = { admin: a, apiErrors: t.apiErrors };
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-extrabold">{a.deliveryTitle}</h1>
        <p className="max-w-prose text-slate">{a.deliveryLead}</p>
      </header>
      {zones.length === 0 ? <p>{a.zonesNone}</p> : null}
      {zones.map((zone) => (
        <section key={zone.id} aria-label={zone.name_en} className="space-y-4 rounded-card border border-line bg-white p-4">
          <h2 className="text-lg font-bold">
            {lang === "am" ? zone.name_am : zone.name_en} <span className="font-normal text-slate">({zone.code})</span>
            {!zone.is_active ? <span className="ml-2 rounded-full border border-clay px-2 py-0.5 text-sm text-clay">{a.zoneOff}</span> : null}
          </h2>
          <ZoneForm zone={zone} t={text} />
          <div className="space-y-2 border-t border-line pt-3">
            <h3 className="font-bold">{a.ratesTitle}</h3>
            <div className="grid gap-4 md:grid-cols-2">
              {METHODS.map((method) => {
                const rate = zone.rates.find((r) => r.method === method);
                return (
                  <div key={method} className="space-y-2">
                    <p className="font-semibold">{codeLabel(t, "deliveryMode", method)}: <span className="font-normal">{rate ? fill(a.rateLine, { fee: formatPrice(rate.fee_santim, lang), hours: rate.promised_hours }) : a.rateNone}</span></p>
                    <RateForm zoneId={zone.id} method={method} rate={rate} t={text} />
                  </div>
                );
              })}
            </div>
          </div>
          <div className="space-y-2 border-t border-line pt-3">
            <h3 className="font-bold">{a.areasTitle}</h3>
            <ul className="grid gap-2 sm:grid-cols-2">
              {zone.areas.map((area) => (
                <li key={area.id} className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line p-2">
                  <span className={area.is_active ? "" : "text-slate line-through"}>{lang === "am" ? area.name_am : area.name_en}</span>
                  <AreaSwitch areaId={area.id} active={area.is_active} t={text} />
                </li>
              ))}
            </ul>
            <NewAreaForm zoneId={zone.id} t={text} />
          </div>
        </section>
      ))}
      <section className="rounded-card border border-ink bg-white p-4">
        <NewZoneForm t={text} />
      </section>
    </div>
  );
}
