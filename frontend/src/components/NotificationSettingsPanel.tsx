import { playTestAlertTone } from "../alertSound";
import type { BrowserNotificationPermission } from "../useNotificationCenter";
import { KNOWN_RULES, RULE_LABELS, type NotificationSettings } from "../notificationSettings";

interface Props {
  settings: NotificationSettings;
  onChange: (settings: NotificationSettings) => void;
  permission: BrowserNotificationPermission;
  onRequestPermission: () => void;
}

function permissionLabel(permission: BrowserNotificationPermission): string {
  switch (permission) {
    case "granted":
      return "Browser notifications enabled";
    case "denied":
      return "Browser notifications blocked";
    case "unsupported":
      return "Notifications unsupported in this browser";
    default:
      return "Enable browser notifications";
  }
}

export function NotificationSettingsPanel({ settings, onChange, permission, onRequestPermission }: Props) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onRequestPermission}
          disabled={permission === "granted" || permission === "unsupported"}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
        >
          {permissionLabel(permission)}
        </button>
        {permission === "denied" && (
          <span className="text-xs text-red-400">
            Blocked in your browser's site settings — re-enable it there to get push alerts.
          </span>
        )}

        <button
          type="button"
          onClick={playTestAlertTone}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm text-slate-200"
        >
          Test sound
        </button>

        <label className="flex items-center gap-1.5 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={settings.muted}
            onChange={(e) => onChange({ ...settings, muted: e.target.checked })}
            className="accent-emerald-500"
          />
          Mute sound
        </label>

        <label className="flex items-center gap-1.5 text-sm text-slate-300">
          Cooldown
          <input
            type="number"
            min={0}
            step={0.5}
            value={settings.cooldownMinutes}
            onChange={(e) => {
              const value = Number(e.target.value);
              onChange({
                ...settings,
                cooldownMinutes: Number.isFinite(value) && value >= 0 ? value : settings.cooldownMinutes,
              });
            }}
            className="w-16 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
          />
          min
        </label>
      </div>

      <div className="flex flex-wrap gap-4">
        <span className="text-sm text-slate-400">Notify on:</span>
        {KNOWN_RULES.map((rule) => (
          <label key={rule} className="flex items-center gap-1.5 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={settings.enabledRules[rule] ?? true}
              onChange={(e) =>
                onChange({
                  ...settings,
                  enabledRules: { ...settings.enabledRules, [rule]: e.target.checked },
                })
              }
              className="accent-emerald-500"
            />
            {RULE_LABELS[rule] ?? rule}
          </label>
        ))}
      </div>
    </div>
  );
}
