import { addTicker, removeTicker } from "./api";
import { BarTable } from "./components/BarTable";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { LiveChartPanel } from "./components/LiveChartPanel";
import { TickerControls } from "./components/TickerControls";
import { useBackendSocket } from "./useBackendSocket";

function App() {
  const { socketState, ibkrState, ibkrError, tickers, bars, barsBySymbol, tickerErrors } =
    useBackendSocket();

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50">Scalp Dashboard</h1>
          <p className="text-sm text-slate-400">
            Live 1-minute candlesticks streamed straight from IBKR TWS/Gateway.
          </p>
        </div>
        <ConnectionStatus socketState={socketState} ibkrState={ibkrState} ibkrError={ibkrError} />
      </header>

      <LiveChartPanel tickers={tickers} barsBySymbol={barsBySymbol} />

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
