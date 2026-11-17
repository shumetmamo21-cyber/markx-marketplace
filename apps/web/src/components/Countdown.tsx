"use client";

import { useSyncExternalStore } from "react";

// The answer countdown on a new order (blueprint I.5). The server renders the
// deadline as a time; the browser then shows the minutes left, updated twice
// a minute.
const TICK = 30_000;
function subscribe(callback: () => void) {
  const id = setInterval(callback, TICK);
  return () => clearInterval(id);
}
const tick = () => Math.floor(Date.now() / TICK);
const serverTick = () => null;

export function Countdown({ deadline, byText, leftText, lateText }: { deadline: string; byText: string; leftText: string; lateText: string }) {
  const now = useSyncExternalStore(subscribe, tick, serverTick);
  if (now === null) return <span>{byText}</span>;
  const minutes = Math.ceil((new Date(deadline).getTime() - now * TICK) / 60_000);
  if (minutes <= 0) return <span className="font-semibold text-clay">{lateText}</span>;
  return <span className="font-semibold">{leftText.replace("{minutes}", String(minutes))}</span>;
}
