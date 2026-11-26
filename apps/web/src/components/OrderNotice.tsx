import { noticePoints, type OrderNotice as Notice } from "@/lib/order-notice";

// C-27 (blueprint D.10; D-110): the notice the buyer reads right above
// "Place order", in their language. The words come from the API's review
// step; this only lays them out.
export function OrderNotice({ notice, id }: { notice: Notice; id: string }) {
  return (
    <section aria-labelledby={id} data-order-notice={notice.version} className="space-y-2 rounded-card border border-line bg-paper p-3">
      <h3 id={id} className="font-bold">{notice.title}</h3>
      <ul className="list-disc space-y-1 ps-5 text-sm">
        {noticePoints(notice).map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
    </section>
  );
}
