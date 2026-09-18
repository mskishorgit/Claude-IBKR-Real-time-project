import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
} from "lightweight-charts";
import type { CandlestickData, IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { computeEma, computeVwap, toUnixSeconds } from "../indicators";
import type { BarMessage } from "../types";

export interface ChartOverlays {
  vwap?: boolean;
  ema9?: boolean;
  ema20?: boolean;
}

const DEFAULT_OVERLAYS: Required<ChartOverlays> = { vwap: true, ema9: true, ema20: true };

interface Props {
  /** Ticker this chart displays. Only used for the empty-state message. */
  symbol: string;
  /** Bars for this symbol, ascending by time, deduped by timestamp (last bar updates in place). */
  bars: BarMessage[];
  /** Total chart height in pixels, including the volume pane. Default 420. */
  height?: number;
  /** Show the volume histogram pane below the candlesticks. Default true. */
  showVolume?: boolean;
  /** Which overlays to draw. Defaults to all three on. */
  overlays?: ChartOverlays;
  /** Denser layout for small tiles (e.g. a watchlist grid): hides axis text, thinner lines. */
  compact?: boolean;
}

const UP_COLOR = "#22c55e";
const DOWN_COLOR = "#ef4444";

export function CandlestickChart({
  symbol,
  bars,
  height = 420,
  showVolume = true,
  overlays = DEFAULT_OVERLAYS,
  compact = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema9SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const hasFitRef = useRef(false);

  const vwapOn = overlays.vwap ?? DEFAULT_OVERLAYS.vwap;
  const ema9On = overlays.ema9 ?? DEFAULT_OVERLAYS.ema9;
  const ema20On = overlays.ema20 ?? DEFAULT_OVERLAYS.ema20;

  // Build the chart + series once per structural config change (volume pane
  // on/off, compact layout). Data is applied in the effect below so we don't
  // tear down and rebuild the chart on every incoming bar.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
        fontSize: compact ? 10 : 12,
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.08)" },
        horzLines: { color: "rgba(148, 163, 184, 0.08)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.2)", visible: !compact },
      timeScale: {
        borderColor: "rgba(148, 163, 184, 0.2)",
        timeVisible: true,
        secondsVisible: false,
        visible: !compact,
      },
      handleScroll: !compact,
      handleScale: !compact,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderVisible: false,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
      priceLineVisible: true,
      priceLineWidth: 2,
      priceLineStyle: LineStyle.Dashed,
      priceLineColor: "#38bdf8",
      lastValueVisible: true,
    });

    let volumeSeries: ISeriesApi<"Histogram"> | null = null;
    if (showVolume) {
      volumeSeries = chart.addSeries(
        HistogramSeries,
        {
          priceFormat: { type: "volume" },
          lastValueVisible: false,
          priceLineVisible: false,
        },
        1,
      );
      chart.panes()[1]?.setStretchFactor(compact ? 0.25 : 0.3);
      chart.panes()[0]?.setStretchFactor(compact ? 0.75 : 0.7);
    }

    const vwapSeries = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: !compact,
      crosshairMarkerVisible: !compact,
    });
    const ema9Series = chart.addSeries(LineSeries, {
      color: "#38bdf8",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: !compact,
      crosshairMarkerVisible: !compact,
    });
    const ema20Series = chart.addSeries(LineSeries, {
      color: "#c084fc",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: !compact,
      crosshairMarkerVisible: !compact,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    vwapSeriesRef.current = vwapSeries;
    ema9SeriesRef.current = ema9Series;
    ema20SeriesRef.current = ema20Series;
    hasFitRef.current = false;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      vwapSeriesRef.current = null;
      ema9SeriesRef.current = null;
      ema20SeriesRef.current = null;
    };
  }, [showVolume, compact]);

  // Push data into the existing series whenever bars change.
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries) return;

    const candleData: CandlestickData<UTCTimestamp>[] = bars.map((bar) => ({
      time: toUnixSeconds(bar.timestamp),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    candleSeries.setData(candleData);

    volumeSeriesRef.current?.setData(
      bars.map((bar) => ({
        time: toUnixSeconds(bar.timestamp),
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(34, 197, 94, 0.5)" : "rgba(239, 68, 68, 0.5)",
      })),
    );

    vwapSeriesRef.current?.setData(vwapOn ? computeVwap(bars) : []);
    ema9SeriesRef.current?.setData(ema9On ? computeEma(bars, 9) : []);
    ema20SeriesRef.current?.setData(ema20On ? computeEma(bars, 20) : []);

    // Only auto-fit the visible range on the initial data load for this
    // mount (e.g. first bars after selecting this symbol), so a live bar
    // streaming in doesn't keep yanking the user's zoom/pan back to "fit all".
    if (!hasFitRef.current && bars.length > 0) {
      chartRef.current?.timeScale().fitContent();
      hasFitRef.current = true;
    }
  }, [bars, vwapOn, ema9On, ema20On]);

  return (
    <div className="relative w-full" style={{ height }}>
      <div ref={containerRef} className="h-full w-full" />
      {bars.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-500">
          Waiting for bar data for {symbol}…
        </div>
      )}
    </div>
  );
}
