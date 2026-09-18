import { useState } from "react";
import { addTicker, closeOptionPosition, removeTicker } from "./api";
import { BarTable } from "./components/BarTable";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { LiveChartPanel } from "./components/LiveChartPanel";
import { NotificationSettingsPanel } from "./components/NotificationSettingsPanel";
import { OptionsPanel } from "./components/OptionsPanel";
import { SignalAlertTray } from "./components/SignalAlertTray";
import { TickerControls } from "./components/TickerControls";
import { TradingModeBanner } from "./components/TradingModeBanner";
import { useBackendSocket } from "./useBackendSocket";
import { useNotificationCenter } from "./useNotificationCenter";
import { useOptionsChainStream } from "./useOptionsChainStream";
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
  const { quotesByKey } = useOptionsChainStream();
  const { positions } = usePositionsStream();

  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

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

      <TradingModeBanner
        status={tradingSafety.status}
        pending={tradingSafety.pending}
        onSetArmed={tradingSafety.setArmed}
      />
      {tradingSafety.error && <p className="text-sm text-red-400">{tradingSafety.error}</p>}

      <LiveChartPanel
        tickers={tickers}
        barsBySymbol={barsBySymbol}
        selectedSymbol={selectedSymbol}
        onSelectSymbol={setSelectedSymbol}
      />

      <OptionsPanel
        symbol={selectedSymbol}
        quotesByKey={quotesByKey}
        positions={positions}
        onClosePosition={async (positionId) => {
          await closeOptionPosition(positionId);
        }}
      />

      <section className="flex flex-col gap-3 rounded-lg border border-slate-800 p-4">
        <h2 className="text-sm font-medium text-slate-300">Tracked tickers</h2>
        <TickerControls
          tickers={tickers}
          onAdd={async (symbol) => {
            await addTicker(symbol);
          }}
          onRemove={async (symbol) => {
            await removeTicker(symbol);
          }}
        />
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
