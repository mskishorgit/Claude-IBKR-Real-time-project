import type { UTCTimestamp } from "lightweight-charts";
import type { BarMessage } from "./types";

export interface IndicatorPoint {
  time: UTCTimestamp;
  value: number;
}

export function toUnixSeconds(timestamp: string): UTCTimestamp {
  return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
}

/** Standard exponential moving average over bar close prices. */
export function computeEma(bars: BarMessage[], period: number): IndicatorPoint[] {
  if (bars.length === 0) return [];
  const k = 2 / (period + 1);
  const out: IndicatorPoint[] = new Array(bars.length);
  let ema = bars[0].close;
  for (let i = 0; i < bars.length; i++) {
    const price = bars[i].close;
    ema = i === 0 ? price : price * k + ema * (1 - k);
    out[i] = { time: toUnixSeconds(bars[i].timestamp), value: ema };
  }
  return out;
}

/**
 * Volume-weighted average price, reset at the start of each session.
 * "Session" is approximated as the bar timestamp's UTC calendar day, which is
 * good enough for a single continuous trading session but does not account
 * for exchange-specific session boundaries or overnight/extended-hours bars.
 */
export function computeVwap(bars: BarMessage[]): IndicatorPoint[] {
  const out: IndicatorPoint[] = new Array(bars.length);
  let cumulativePV = 0;
  let cumulativeVolume = 0;
  let currentDay = "";
  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];
    const day = bar.timestamp.slice(0, 10);
    if (day !== currentDay) {
      currentDay = day;
      cumulativePV = 0;
      cumulativeVolume = 0;
    }
    const typicalPrice = (bar.high + bar.low + bar.close) / 3;
    cumulativePV += typicalPrice * bar.volume;
    cumulativeVolume += bar.volume;
    const vwap = cumulativeVolume > 0 ? cumulativePV / cumulativeVolume : typicalPrice;
    out[i] = { time: toUnixSeconds(bar.timestamp), value: vwap };
  }
  return out;
}
