import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Stars } from "@/components/Reviews";
import { SellerReplyForm } from "@/components/SellerReplyForm";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

const PER_PAGE = 20;

// The shop's reviews (blueprint S-16): published ones and ones MarkX hid,
// newest first, without the buyer's name or order. A reply form appears where
// the API says the shop may reply (D-072); the shop can never remove one.
export default async function SellerReviewsPage({ params, searchParams }: PageProps<"/[lang]/seller/[sellerId]/reviews">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const raw = (await searchParams).before;
  const before = (Array.isArray(raw) ? raw[0] : raw) ?? "";
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/seller/{seller_id}/reviews", {
    params: { path: { seller_id: sellerId }, query: { lang, limit: PER_PAGE, before: /^[0-9a-f-]{36}$/.test(before) ? before : undefined } },
  });
  const s = t.seller;
  if (response.status === 403) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const reviews = data ?? [];
  const replyText = { seller: t.seller, apiErrors: t.apiErrors };
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-extrabold">{s.reviewsTitle}</h1>
      <p className="text-slate">{s.reviewsLead}</p>
      {reviews.length === 0 ? <p>{s.reviewsNone}</p> : null}
      <ul className="space-y-3">
        {reviews.map((review) => (
          <li key={review.id} className="space-y-2 rounded-card border border-line bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-bold">{review.title}{review.variant_label ? ` (${review.variant_label})` : ""}</p>
                <p className="text-sm text-slate">{formatDateTime(review.created_at, lang)}</p>
              </div>
              <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{codeLabel(t, "reviewStatus", review.status)}</span>
            </div>
            <p className="flex flex-wrap gap-x-4 text-sm">
              <span>{t.reviews.product} <Stars value={review.product_rating} t={t} /></span>
              <span>{t.reviews.seller} <Stars value={review.seller_rating} t={t} /></span>
            </p>
            {review.body ? <p className="whitespace-pre-line break-words">{review.body}</p> : null}
            {review.can_reply ? (
              <SellerReplyForm sellerId={sellerId} reviewId={review.id} current={review.seller_reply} t={replyText} />
            ) : review.seller_reply ? (
              <div className="rounded-card border-l-4 border-ink bg-paper p-3 text-sm">
                <p className="font-semibold">{s.replyLabel}</p>
                <p className="whitespace-pre-line break-words">{review.seller_reply}</p>
              </div>
            ) : (
              <p className="text-sm text-slate">{s.replyHint}</p>
            )}
          </li>
        ))}
      </ul>
      {reviews.length === PER_PAGE ? (
        <p><Link href={`/${lang}/seller/${sellerId}/reviews?before=${reviews[reviews.length - 1]?.id}`} className="inline-flex min-h-12 items-center font-semibold underline">{s.olderReviews}</Link></p>
      ) : null}
    </div>
  );
}
