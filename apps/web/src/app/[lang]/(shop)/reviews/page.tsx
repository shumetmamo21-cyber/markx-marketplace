import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ReviewForm } from "@/components/ReviewForm";
import { Stars } from "@/components/Reviews";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

// The buyer's reviews (blueprint C-18): what is waiting to be rated, and what
// they wrote, with what MarkX and the shop did with it. Forms appear only
// where the API says the buyer may act (D-072); it checks again.
export default async function MyReviewsPage({ params }: PageProps<"/[lang]/reviews">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  if (!(await getMe())) redirect(`/${lang}/sign-in?next=/${lang}/reviews`);
  const t = await getMessages(lang);
  const api = await serverApi();
  const [pending, mine] = await Promise.all([
    api.GET("/api/v1/me/reviews/pending", { params: { query: { lang } } }),
    api.GET("/api/v1/me/reviews", { params: { query: { lang } } }),
  ]);
  const r = t.reviews;
  const formText = { reviews: t.reviews, apiErrors: t.apiErrors };
  const waiting = pending.data ?? [];
  const written = mine.data ?? [];

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <section aria-labelledby="pending" className="space-y-3">
        <h1 id="pending" className="text-2xl font-extrabold">{r.pendingTitle}</h1>
        {waiting.length === 0 ? <p className="text-slate">{r.pendingNone}</p> : null}
        <ul className="space-y-3">
          {waiting.map((item) => (
            <li key={item.order_item_id} className="space-y-3 rounded-card border border-line bg-white p-4">
              <div>
                <p className="font-bold">{item.title}{item.variant_label ? ` (${item.variant_label})` : ""}</p>
                <p className="text-sm text-slate">
                  <Link href={`/${lang}/orders/${item.order_id}`} className="underline">{fill(r.order, { code: item.order_code })}</Link>
                  {" · "}{fill(r.rateBy, { date: formatDateTime(item.review_until, lang) })}
                </p>
              </div>
              <ReviewForm target={{ kind: "write", orderId: item.order_id, itemId: item.order_item_id }} t={formText} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="mine" className="space-y-3">
        <h2 id="mine" className="text-xl font-bold">{r.mine}</h2>
        {written.length === 0 ? <p className="text-slate">{r.empty}</p> : null}
        <ul className="space-y-3">
          {written.map((review) => (
            <li key={review.id} className="space-y-2 rounded-card border border-line bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-bold">{review.title}{review.variant_label ? ` (${review.variant_label})` : ""}</p>
                  {review.order_id && review.order_code ? (
                    <p className="text-sm text-slate"><Link href={`/${lang}/orders/${review.order_id}`} className="underline">{fill(r.order, { code: review.order_code })}</Link></p>
                  ) : null}
                </div>
                <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{codeLabel(t, "reviewStatus", review.status)}</span>
              </div>
              <p className="flex flex-wrap gap-x-4 text-sm">
                <span>{r.product} <Stars value={review.product_rating} t={t} /></span>
                <span>{r.seller} <Stars value={review.seller_rating} t={t} /></span>
              </p>
              {review.body ? <p className="whitespace-pre-line break-words">{review.body}</p> : null}
              {review.status === "held" ? <p className="text-sm text-slate">{r.heldNote}</p> : null}
              {review.status === "hidden" ? <p className="text-sm font-semibold text-clay">{fill(r.hiddenNote, { reason: review.moderation_reason ?? "" })}</p> : null}
              {review.seller_reply ? (
                <div className="rounded-card border-l-4 border-ink bg-paper p-3 text-sm">
                  <p className="font-semibold">{r.reply}</p>
                  <p className="whitespace-pre-line break-words">{review.seller_reply}</p>
                </div>
              ) : null}
              {review.can_edit ? (
                <details>
                  <summary className="inline-flex min-h-12 cursor-pointer items-center font-semibold underline">{r.edit}</summary>
                  <ReviewForm
                    target={{ kind: "edit", reviewId: review.id, productRating: review.product_rating, sellerRating: review.seller_rating, body: review.body }}
                    t={formText}
                  />
                </details>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
