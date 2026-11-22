// The price-history chart on a product page (blueprint C-21, I.5; D-106).
// Drawn on the server as plain SVG: no script, readable without JavaScript,
// and light on a slow phone (D.26). One small chart per condition, so a line
// is never told apart by its colour; every value is also in the table.
// The API decides every number (the lowest price each day, from the prices
// recorded); this only draws them.
import type { PriceHistory } from "@/lib/api/types";
import { formatDate, formatPrice } from "@/lib/format";
import { fill, type Locale, type Messages } from "@/lib/i18n";
import { chartGeometry, CHART } from "@/lib/price-chart";

type Text = Pick<Messages, "product" | "condition">;

function conditionLabel(t: Text, condition: string): string {
  return condition in t.condition ? t.condition[condition as keyof Messages["condition"]] : condition;
}

export function PriceHistoryChart({ history, lang, t }: { history: PriceHistory; lang: Locale; t: Text }) {
  if (history.series.length === 0) return null;
  const p = t.product;
  return (
    <section aria-labelledby="price-history" className="space-y-3">
      <h2 id="price-history" className="text-lg font-bold">{p.priceHistory}</h2>
      <p className="text-sm text-slate">
        {fill(p.priceHistoryLead, { days: history.days })} {fill(p.priceHistoryRange, { from: formatDate(history.from_day, lang), to: formatDate(history.to_day, lang) })}
      </p>
      <ul className="grid gap-3 md:grid-cols-2">
        {history.series.map((series) => {
          const shape = chartGeometry(series.steps, history.from_day, history.to_day);
          const label = conditionLabel(t, series.condition);
          const summary = fill(p.priceHistorySummary, {
            current: formatPrice(series.current_santim, lang),
            lowest: formatPrice(series.lowest_santim, lang),
            highest: formatPrice(series.highest_santim, lang),
          });
          return (
            <li key={series.condition} className="space-y-2 rounded-card border border-line bg-white p-4">
              <h3 className="font-bold">{label}</h3>
              <p className="text-sm">{summary}</p>
              {series.steps.length === 1 ? <p className="text-sm text-slate">{p.priceHistorySteady}</p> : null}
              <svg viewBox={`0 0 ${CHART.width} ${CHART.height}`} className="w-full max-w-md" role="img" aria-label={`${p.priceHistory}, ${label}: ${summary}`}>
                {shape.gridlines.map((y) => (
                  <line key={y} x1={0} x2={CHART.width} y1={y} y2={y} stroke="#e6e0d6" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                ))}
                <text x={0} y={shape.highLabelY} fontSize={11} fill="#5b6675" style={{ fontVariantNumeric: "tabular-nums" }}>{formatPrice(series.highest_santim, lang)}</text>
                {series.highest_santim !== series.lowest_santim ? (
                  <text x={0} y={shape.lowLabelY} fontSize={11} fill="#5b6675" style={{ fontVariantNumeric: "tabular-nums" }}>{formatPrice(series.lowest_santim, lang)}</text>
                ) : null}
                <path d={shape.path} fill="none" stroke="#2a78d6" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                <circle cx={shape.end.x} cy={shape.end.y} r={4} fill="#2a78d6" stroke="#ffffff" strokeWidth={2} />
                {shape.spans.map((span, index) => (
                  <rect key={index} x={span.x} y={0} width={Math.max(span.width, 1)} height={CHART.height} fill="transparent">
                    <title>{fill(p.priceHistoryFrom, { date: formatDate(series.steps[index]?.day ?? "", lang), price: formatPrice(series.steps[index]?.price_santim ?? 0, lang) })}</title>
                  </rect>
                ))}
              </svg>
              <details className="text-sm">
                <summary className="min-h-12 cursor-pointer py-3 font-semibold">{p.priceHistoryTable}</summary>
                <table className="w-full text-left">
                  <thead>
                    <tr><th className="py-1 pr-3 font-semibold">{p.priceHistoryDay}</th><th className="py-1 font-semibold">{p.priceHistoryPrice}</th></tr>
                  </thead>
                  <tbody>
                    {series.steps.map((step) => (
                      <tr key={step.day} className="border-t border-line">
                        <td className="py-1 pr-3">{formatDate(step.day, lang)}</td>
                        <td className="price py-1">{formatPrice(step.price_santim, lang)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
