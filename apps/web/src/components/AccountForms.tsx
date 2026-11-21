"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { NewAddress } from "@/components/Checkout";
import { browserApi, errorCode } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { apiErrorText, type Locale, type Messages } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

// The buyer's account (blueprint I.5, C-08, H.5): each form sends the
// person's choice and shows the API's answer in words.

type T = Pick<Messages, "account" | "apiErrors">;
type Zone = components["schemas"]["ZoneOut"];

const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
const button = "min-h-12 rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60";

function AccountForm({ t, onSubmit, children, label, done, quiet = false }: { t: T; onSubmit: (form: FormData) => Promise<{ error?: unknown }>; children?: ReactNode; label: string; done?: string; quiet?: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string; code: string } | null>(null);
  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const element = event.currentTarget;
        setBusy(true);
        setMessage(null);
        const { error } = await onSubmit(new FormData(element));
        setBusy(false);
        if (error) return setMessage({ ok: false, text: apiErrorText(t, errorCode(error)), code: errorCode(error) });
        element.reset();
        setMessage({ ok: true, text: done ?? t.account.saved, code: "" });
        router.refresh();
      }}
    >
      {children}
      <button type="submit" disabled={busy} className={quiet ? "min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60" : button}>{label}</button>
      {message?.ok ? <p role="status" className="font-semibold">{message.text}</p> : null}
      {message && !message.ok ? <ProblemNotice code={message.code} text={message.text} retry="submit" busy={busy} /> : null}
    </form>
  );
}

export function ProfileForm({ name, language, t }: { name: string | null; language: string; t: T }) {
  const a = t.account;
  return (
    <AccountForm
      t={t}
      label={a.save}
      onSubmit={(form) => browserApi.PATCH("/api/v1/me", { body: { name: String(form.get("name") ?? "").trim(), language: String(form.get("language")) } })}
    >
      <label className="block space-y-1">
        <span className="block text-sm font-semibold">{a.name}</span>
        <input name="name" maxLength={80} autoComplete="name" defaultValue={name ?? ""} className={field} />
      </label>
      <fieldset className="space-y-1">
        <legend className="text-sm font-semibold">{a.language}</legend>
        {(["am", "en"] as const).map((code) => (
          <label key={code} className="flex min-h-12 items-center gap-3">
            <input type="radio" name="language" value={code} defaultChecked={language === code} className="h-5 w-5" />
            {code === "am" ? a.languageAm : a.languageEn}
          </label>
        ))}
      </fieldset>
    </AccountForm>
  );
}

export function AddAddress({ lang, zones, t }: { lang: Locale; zones: Zone[]; t: Pick<Messages, "checkout" | "apiErrors"> }) {
  const router = useRouter();
  return <NewAddress lang={lang} t={t} zones={zones} onSaved={() => router.refresh()} />;
}

export function RemoveAddress({ addressId, t }: { addressId: string; t: T }) {
  return (
    <AccountForm t={t} quiet label={t.account.addressRemove} onSubmit={() => browserApi.DELETE("/api/v1/me/addresses/{address_id}", { params: { path: { address_id: addressId } } })} />
  );
}

export function MarkNotificationsRead({ t }: { t: T }) {
  return <AccountForm t={t} quiet label={t.account.markRead} onSubmit={() => browserApi.POST("/api/v1/me/notifications/read", {})} />;
}

export function DataRequestForm({ t, kinds }: { t: T; kinds: Messages["labels"]["dataRequestKind"] }) {
  const a = t.account;
  return (
    <AccountForm
      t={t}
      label={a.requestSend}
      done={a.requestSent}
      onSubmit={(form) => {
        const note = String(form.get("note") ?? "").trim();
        return browserApi.POST("/api/v1/me/data-requests", {
          body: { kind: String(form.get("kind")) as components["schemas"]["DataRequestIn"]["kind"], note: note || null },
        });
      }}
    >
      <fieldset className="space-y-1">
        <legend className="text-sm font-semibold">{a.requestKind}</legend>
        {(["export", "correct", "delete"] as const).map((kind) => (
          <label key={kind} className="flex min-h-12 items-center gap-3">
            <input type="radio" name="kind" value={kind} defaultChecked={kind === "export"} className="h-5 w-5" />
            {kinds[kind]}
          </label>
        ))}
      </fieldset>
      <label className="block space-y-1">
        <span className="block text-sm font-semibold">{a.requestNote}</span>
        <textarea name="note" maxLength={5000} rows={2} className="w-full rounded-card border border-line bg-white p-3" />
      </label>
    </AccountForm>
  );
}

export function SignOutEverywhere({ home, t }: { home: string; t: T }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ code: string; text: string } | null>(null);
  const signOut = async () => {
    setBusy(true);
    setProblem(null);
    const { error } = await browserApi.POST("/api/v1/auth/sign-out-everywhere", {});
    setBusy(false);
    if (error) return setProblem({ code: errorCode(error), text: apiErrorText(t, errorCode(error)) });
    router.push(home);
    router.refresh();
  };
  return (
    <div className="space-y-1">
      <button
        type="button"
        disabled={busy}
        onClick={signOut}
        className="min-h-12 rounded-card border border-clay px-4 font-semibold text-clay disabled:opacity-60"
      >
        {t.account.signOutEverywhere}
      </button>
      {problem ? <ProblemNotice code={problem.code} text={problem.text} retry={() => void signOut()} busy={busy} /> : null}
    </div>
  );
}
