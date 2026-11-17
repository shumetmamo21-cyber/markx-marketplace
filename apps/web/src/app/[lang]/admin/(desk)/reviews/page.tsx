import Link from "next/link";
import { notFound } from "next/navigation";

import { ModerateReviewForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

const STATUSES = ["held", "published", "hidden"] as const;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PAGE = 50;

// Review moderation (blueprint D.15, AD-12; D-066): held reviews first. Staff
// publish or hide with a written reason; the API keeps it in the audit log and
// recounts the ratings.
export default async function ReviewsPage({ params, searchParams }: PageProps<"/[lang]/admin/reviews">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const query = await searchParams;
  const status = STATUSES.find((s) => s === query.status) ?? "held";
  const before = typeof query.before === "string" && UUID.test(query.before) ? query.before : undefined;
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/reviews", {
    params: { query: { status, limit: PAGE, lang, ...(before ? { before } : {}) } },
  });
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const rows = data ?? [];
  const last = rows.at(-1);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.reviewsTitle}</h1>
      <nav aria-label={a.statusFilter} className="flex flex-wrap gap-2">
        {STATUSES.map((s) => (
          <Link key={s} href={`/${lang}/admin/reviews?status=${s}`} aria-current={s === status ? "page" : undefined} className={`min-h-12 rounded-full border px-4 py-3 font-semibold ${s === status ? "border-ink bg-ink text-paper" : "border-line bg-white"}`}>
            {codeLabel(t, "reviewStatus", s)}
          </Link>
        ))}
      </nav>
      {rows.length === 0 ? <p className="text-slate">{a.noReviews}</p> : null}
      <ul className="space-y-3">
        {rows.map((review) => (
          <li key={review.id} className="space-y-2 rounded-card border border-line bg-white p-4">
            <p className="font-bold">{review.title} <span className="font-normal text-slate">· {review.variant_label} · {review.store_slug}</span></p>
            <p className="text-sm text-slate">{fill(a.ratings, { product: review.product_rating, seller: review.seller_rating })} · {formatDateTime(review.created_at, lang)}</p>
            {review.body ? <p className="whitespace-pre-line">{review.body}</p> : null}
            {review.held_reason ? <p className="text-sm font-semibold text-clay">{fill(a.heldBecause, { reason: codeLabel(t, "heldReason", review.held_reason) })}</p> : null}
            {review.moderation_reason ? <p className="text-sm">{fill(a.moderated, { reason: review.moderation_reason })}</p> : null}
            {review.seller_reply ? <p className="text-sm">{fill(a.sellerReplied, { reply: review.seller_reply })}</p> : null}
            <ModerateReviewForm reviewId={review.id} status={review.status} t={text} />
          </li>
        ))}
      </ul>
      {rows.length === PAGE && last ? (
        <Link href={`/${lang}/admin/reviews?status=${status}&before=${last.id}`} className="inline-block min-h-12 rounded-card border border-ink px-4 py-3 font-semibold">{a.older}</Link>
      ) : null}
    </div>
  );
}
