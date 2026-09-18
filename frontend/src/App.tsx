import { useState } from "react";
import { addTicker, closeOptionPosition, removeTicker } from "./api";
import { AccountMismatchBanner } from "./components/AccountMismatchBanner";
import { AccountSummaryStrip } from "./components/AccountSummaryStrip";
import { BarTable } from "./components/BarTable";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { JournalPanel } from "./components/JournalPanel";
import { KillSwitchControl } from "./components/KillSwitchControl";
import { LiveChartPanel } from "./components/LiveChartPanel";
import { NotificationSettingsPanel } from "./components/NotificationSettingsPanel";
import { OptionsPanel } from "./components/OptionsPanel";
import { PortfolioTable } from "./components/PortfolioTable";
import { SignalAlertTray } from "./components/SignalAlertTray";
import { StaleBadge } from "./components/StaleBadge";
import { StaleDataBanner } from "./components/StaleDataBanner";
import { TradingModeBanner } from "./components/TradingModeBanner";
import { WatchlistGrid } from "./components/WatchlistGrid";
import { isDataStale } from "./dataFreshness";
import { useBackendSocket } from "./useBackendSocket";
import { useJournalStream } from "./useJournalStream";
import { useNotificationCenter } from "./useNotificationCenter";
import { useOptionsChainStream } from "./useOptionsChainStream";
import { usePortfolioStream } from "./usePortfolioStream";
import { usePositionsStream } from "./usePositionsStream";
import { useSignalStream } from "./useSignalStream";
import { useTradingSafety } from "./useTradingSafety";

function App() {
  const { socketState, ibkrState, ibkrError, tickers, bars, barsBySymbol, tickerErrors } =
    useBackendSocket();
  const { signals } = useSignalStream();
  const { settings, setSettings, toasts, dismissToast, permission, requestPermission } =
    useNotificationCenter(signals);
  const tradingSafety = useTradingSafety();
  const { quotesByKey, socketState: optionsSocketState } = useOptionsChainStream();
  const { positions, socketState: positionsSocketState } = usePositionsStream();
  const portfolio = usePortfolioStream();
  const { version: journalVersion } = useJournalStream();

  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  // Whether anything currently on screen could be frozen rather than live —
  // see dataFreshness.ts. Drives both the page-level banner and dimming the
  // individual price/position sections below.
  const dataStale = isDataStale(ibkrState, [
    socketState,
    portfolio.socketState,
    positionsSocketState,
    optionsSocketState,
  ]);

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col gap-6 px-4 py-8">
      <SignalAlertTray toasts={toasts} onDismiss={dismissToast} onSelectSymbol={setSelectedSymbol} />

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50">Scalp Dashboard</h1>
          <p className="text-sm text-slate-400">
            Live 1-minute candlesticks streamed straight from IBKR TWS/Gateway.
          </p>
        </div>
        <ConnectionStatus socketState={socketState} ibkrState={ibkrState} ibkrError={ibkrError} />
      </header>

      <StaleDataBanner ibkrState={ibkrState} ibkrError={ibkrError} backendReachable={socketState === "open"} />

      <KillSwitchControl
        status={tradingSafety.status}
        pending={tradingSafety.pending}
        lastResult={tradingSafety.lastKillSwitchResult}
        onEngage={tradingSafety.engageKillSwitch}
        onReset={tradingSafety.resetKillSwitch}
      />

      <AccountMismatchBanner status={tradingSafety.status} />

      <TradingModeBanner
        status={tradingSafety.status}
        pending={tradingSafety.pending}
        onSetArmed={tradingSafety.setArmed}
      />
      {tradingSafety.error && <p className="text-sm text-red-400">{tradingSafety.error}</p>}

      <section className={`flex flex-col gap-3 rounded-lg border border-slate-800 p-4 ${dataStale ? "opacity-60" : ""}`}>
        <h2 className="flex items-center gap-2 text-sm font-medium text-slate-300">
          Account summary
          {dataStale && <StaleBadge />}
        </h2>
        <AccountSummaryStrip summary={portfolio.summary} />
      </section>

      <section className={`flex flex-col gap-3 rounded-lg border border-slate-800 p-4 ${dataStale ? "opacity-60" : ""}`}>
        <h2 className="flex items-center gap-2 text-sm font-medium text-slate-300">
          Watchlist
          {dataStale && <StaleBadge />}
        </h2>
        <WatchlistGrid
          tickers={tickers}
          barsBySymbol={barsBySymbol}
          signals={signals}
          selectedSymbol={selectedSymbol}
          onSelectSymbol={setSelectedSymbol}
          onAdd={async (symbol) => {
            await addTicker(symbol);
          }}
          onRemove={async (symbol) => {
            await removeTicker(symbol);
          }}
        />
      </section>

      <div className={dataStale ? "opacity-60" : ""}>
        <LiveChartPanel
          tickers={tickers}
          barsBySymbol={barsBySymbol}
          selectedSymbol={selectedSymbol}
          onSelectSymbol={setSelectedSymbol}
        />
      </div>

      <OptionsPanel
        symbol={selectedSymbol}
        quotesByKey={quotesByKey}
        positions={positions}
        onClosePosition={async (positionId) => {
          await closeOptionPosition(positionId);
        }}
      />

      <section className={`flex flex-col gap-3 rounded-lg border border-slate-800 p-4 ${dataStale ? "opacity-60" : ""}`}>
        <h2 className="flex items-center gap-2 text-sm font-medium text-slate-300">
          Portfolio
          {dataStale && <StaleBadge />}
        </h2>
        <PortfolioTable
          positions={portfolio.positions}
          optionPositions={portfolio.optionPositions}
          summary={portfolio.summary}
        />
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-slate-800 p-4">
        <h2 className="text-sm font-medium text-slate-300">Trading journal</h2>
        <JournalPanel journalVersion={journalVersion} />
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-slate-800 p-4">
        <h2 className="text-sm font-medium text-slate-300">Signal alerts</h2>
        <NotificationSettingsPanel
          settings={settings}
          onChange={setSettings}
          permission={permission}
          onRequestPermission={requestPermission}
        />
      </section>

      {tickerErrors.length > 0 && (
        <section className="flex flex-col gap-2 rounded-lg border border-red-500/30 bg-red-500/5 p-4">
          <h2 className="text-sm font-medium text-red-400">Market data issues</h2>
          <ul className="flex flex-col gap-1 text-xs text-red-300">
            {tickerErrors.map((err, i) => (
              <li key={i}>
                {err.symbol ? `${err.symbol}: ` : ""}
                {err.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      <details className="flex flex-col gap-3 rounded-lg border border-slate-800 p-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-300">
          Raw incoming bars ({bars.length}) — debug feed
        </summary>
        <div className="mt-3">
          <BarTable bars={bars} />
        </div>
      </details>
    </div>
  );
}

export default App;
