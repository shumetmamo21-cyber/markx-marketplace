import { describe, expect, it } from "vitest";

import { CHART, chartGeometry } from "./price-chart";

const WIDTH = CHART.width - CHART.right;

describe("chartGeometry (blueprint C-21)", () => {
  it("draws the lowest price as steps: the highest at the top, the lowest at the bottom", () => {
    const shape = chartGeometry(
      [
        { day: "2026-08-25", price_santim: 1_850_000 },
        { day: "2026-10-09", price_santim: 1_790_000 },
        { day: "2026-11-20", price_santim: 1_820_000 },
      ],
      "2026-08-25",
      "2026-11-22",
    );
    // 89 days wide: 9 October is day 45, 20 November day 87.
    const x45 = Math.round((45 / 89) * WIDTH * 10) / 10;
    const x87 = Math.round((87 / 89) * WIDTH * 10) / 10;
    // 18,200 is halfway between the highest (18,500) and the lowest (17,900).
    const middle = (CHART.top + CHART.bottom) / 2;
    expect(shape.path).toBe(`M0 ${CHART.top}H${x45}V${CHART.bottom}H${x87}V${middle}H${WIDTH}`);
    expect(shape.end).toEqual({ x: WIDTH, y: middle });
    expect(shape.gridlines).toEqual([CHART.top, CHART.bottom]);
    // One hover area per step, from its day to the next change, then to the end.
    expect(shape.spans.map((span) => span.x)).toEqual([0, x45, x87]);
    expect(shape.spans.reduce((sum, span) => sum + span.width, 0)).toBeCloseTo(WIDTH, 0);
  });
  it("starts the line on the day the first offer was made", () => {
    const shape = chartGeometry([{ day: "2026-11-12", price_santim: 990_000 }], "2026-08-25", "2026-11-22");
    expect(shape.path.startsWith(`M${Math.round((79 / 89) * WIDTH * 10) / 10} `)).toBe(true);
  });
  it("draws a price that never changed as a level line in the middle", () => {
    const shape = chartGeometry([{ day: "2026-08-25", price_santim: 1_240_000 }], "2026-08-25", "2026-11-22");
    const middle = (CHART.top + CHART.bottom) / 2;
    expect(shape.path).toBe(`M0 ${middle}H${WIDTH}`);
    expect(shape.gridlines).toEqual([middle]);
  });
  it("keeps a step outside the window inside the chart", () => {
    const shape = chartGeometry([{ day: "2026-01-01", price_santim: 5 }, { day: "2026-12-31", price_santim: 7 }], "2026-08-25", "2026-11-22");
    expect(shape.spans[0]?.x).toBe(0);
    expect(shape.spans[1]?.x).toBe(WIDTH);
  });
});
