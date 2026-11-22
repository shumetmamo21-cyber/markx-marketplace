// The geometry of one price-history chart (blueprint C-21; D-106): where the
// step line, its end and its hover areas go, in the chart's own units. Pure,
// so it is unit-tested; PriceHistoryChart.tsx draws it.

export const CHART = { width: 320, height: 132, top: 16, bottom: 112, right: 8 } as const;

type Step = { day: string; price_santim: number };

function dayNumber(day: string): number {
  const [year, month, date] = day.split("-").map(Number);
  return Math.round(Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1) / 86_400_000);
}

const round = (value: number) => Math.round(value * 10) / 10;

/** A step line: the lowest price stays level until the day it changed, then
 * moves straight to the new price. The highest price is at the top, the
 * lowest at the bottom; a price that never changed is a level line in the
 * middle. The last price carries on to the window's last day. */
export function chartGeometry(steps: Step[], fromDay: string, toDay: string) {
  const first = dayNumber(fromDay);
  const span = Math.max(dayNumber(toDay) - first, 1);
  const plotWidth = CHART.width - CHART.right;
  const x = (day: string) => round((Math.min(Math.max(dayNumber(day) - first, 0), span) / span) * plotWidth);
  const prices = steps.map((step) => step.price_santim);
  const high = Math.max(...prices);
  const low = Math.min(...prices);
  const flat = high === low;
  const y = (price: number) => round(flat ? (CHART.top + CHART.bottom) / 2 : CHART.top + ((high - price) / (high - low)) * (CHART.bottom - CHART.top));
  const path = steps.map((step, index) => (index === 0 ? `M${x(step.day)} ${y(step.price_santim)}` : `H${x(step.day)}V${y(step.price_santim)}`)).join("") + `H${plotWidth}`;
  const spans = steps.map((step, index) => {
    const start = x(step.day);
    const next = steps[index + 1];
    return { x: start, width: round((next ? x(next.day) : plotWidth) - start) };
  });
  return {
    path,
    spans,
    end: { x: plotWidth, y: y(prices[prices.length - 1] ?? low) },
    gridlines: flat ? [y(high)] : [CHART.top, CHART.bottom],
    highLabelY: round((flat ? y(high) : CHART.top) - 5),
    lowLabelY: CHART.bottom + 14,
  };
}
