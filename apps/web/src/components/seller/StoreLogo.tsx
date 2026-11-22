"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, fill, type Messages } from "@/lib/i18n";

import { PhotoUpload } from "../PhotoUpload";
import { ProblemNotice } from "../Resilience";

type Text = { seller: Pick<Messages["seller"], "logoTitle" | "logoLead" | "logoChoose" | "logoUpload" | "logoSaved" | "logoRemove" | "logoRemoved" | "logoNone">; store: Pick<Messages["store"], "logoAlt">; apiErrors: Messages["apiErrors"] };

// The shop's own logo (blueprint S-03; D-106). The API checks the picture,
// strips everything but its pixels and fits it to the logo's size; this
// sends what the person picked, shows the result and offers to remove it.
export function StoreLogo({ sellerId, storeName, logoUrl, t }: { sellerId: string; storeName: string; logoUrl: string | null; t: Text }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string; code: string } | null>(null);
  const s = t.seller;
  const remove = async () => {
    setBusy(true);
    setMessage(null);
    const { error } = await browserApi.DELETE("/api/v1/seller/{seller_id}/store/logo", { params: { path: { seller_id: sellerId } } });
    setBusy(false);
    if (error) {
      setMessage({ ok: false, text: apiErrorText(t, errorCode(error)), code: errorCode(error) });
      return;
    }
    setMessage({ ok: true, text: s.logoRemoved, code: "" });
    router.refresh();
  };
  return (
    <section aria-labelledby="logo" className="space-y-3 rounded-card border border-line bg-white p-4">
      <h2 id="logo" className="text-lg font-bold">{s.logoTitle}</h2>
      <p className="text-sm text-slate">{s.logoLead}</p>
      {logoUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- drawn by the API within 256 px and 40 KB (D-106)
        <img src={logoUrl} alt={fill(t.store.logoAlt, { name: storeName })} width={96} height={96} className="h-24 w-24 rounded-card border border-line bg-white object-contain" />
      ) : (
        <p className="text-sm">{s.logoNone}</p>
      )}
      <PhotoUpload path={`/api/v1/seller/${sellerId}/store/logo`} label={s.logoChoose} send={s.logoUpload} sent={s.logoSaved} t={t} />
      {logoUrl ? (
        <button type="button" onClick={remove} disabled={busy} className="min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60">{s.logoRemove}</button>
      ) : null}
      {message?.ok ? <p role="status" className="font-semibold">{message.text}</p> : null}
      {message && !message.ok ? <ProblemNotice code={message.code} text={message.text} retry={remove} busy={busy} /> : null}
    </section>
  );
}
