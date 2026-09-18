/** Known signal engine rule names (backend/app/signals/rules.py) — used to
 * seed the settings panel's per-rule toggles with sensible defaults, without
 * needing a backend round-trip just to list them. */
export const KNOWN_RULES = ["vwap_reclaim", "ema_cross", "volume_spike_breakout"] as const;

export const RULE_LABELS: Record<string, string> = {
  vwap_reclaim: "VWAP reclaim/rejection",
  ema_cross: "EMA 9/20 cross",
  volume_spike_breakout: "Volume spike breakout",
};

export interface NotificationSettings {
  /** ruleName -> whether it should generate a toast/push/sound alert.
   * A rule absent from this map is treated as enabled (see isRuleEnabled). */
  enabledRules: Record<string, boolean>;
  cooldownMinutes: number;
  muted: boolean;
}

export const DEFAULT_NOTIFICATION_SETTINGS: NotificationSettings = {
  enabledRules: Object.fromEntries(KNOWN_RULES.map((rule) => [rule, true])),
  cooldownMinutes: 2,
  muted: false,
};

export function isRuleEnabled(settings: NotificationSettings, rule: string): boolean {
  return settings.enabledRules[rule] !== false;
}

const STORAGE_KEY = "scalp-dashboard.notification-settings.v1";

export function loadNotificationSettings(): NotificationSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_NOTIFICATION_SETTINGS;
    const parsed = JSON.parse(raw);
    const cooldownMinutes =
      typeof parsed.cooldownMinutes === "number" && parsed.cooldownMinutes >= 0
        ? parsed.cooldownMinutes
        : DEFAULT_NOTIFICATION_SETTINGS.cooldownMinutes;
    return {
      enabledRules: {
        ...DEFAULT_NOTIFICATION_SETTINGS.enabledRules,
        ...(parsed.enabledRules && typeof parsed.enabledRules === "object" ? parsed.enabledRules : {}),
      },
      cooldownMinutes,
      muted: Boolean(parsed.muted),
    };
  } catch {
    return DEFAULT_NOTIFICATION_SETTINGS;
  }
}

export function saveNotificationSettings(settings: NotificationSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // best-effort persistence only — a private window or full storage quota
    // shouldn't break the notification settings themselves.
  }
}
