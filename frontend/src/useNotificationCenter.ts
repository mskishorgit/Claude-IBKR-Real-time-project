import { useEffect, useRef, useState } from "react";
import { playLongAlertTone, playShortAlertTone } from "./alertSound";
import {
  isRuleEnabled,
  loadNotificationSettings,
  saveNotificationSettings,
  type NotificationSettings,
} from "./notificationSettings";
import type { SignalMessage } from "./types";

export interface ToastSignal extends SignalMessage {
  id: string;
}

export type BrowserNotificationPermission = NotificationPermission | "unsupported";

function signalId(signal: SignalMessage): string {
  return `${signal.ticker}|${signal.rule}|${signal.timestamp}`;
}

function browserNotificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** Turns the raw (newest-first) signal stream into: a dismissible toast
 * list, browser push notifications, and audible alerts — all gated by
 * per-rule enable/disable and a per-(ticker,rule) cooldown, per the
 * persisted NotificationSettings. Each incoming signal is processed exactly
 * once, however many times this hook re-renders. */
export function useNotificationCenter(signals: SignalMessage[]) {
  const [settings, setSettingsState] = useState<NotificationSettings>(() => loadNotificationSettings());
  const [toasts, setToasts] = useState<ToastSignal[]>([]);
  const [permission, setPermission] = useState<BrowserNotificationPermission>(() =>
    browserNotificationsSupported() ? Notification.permission : "unsupported",
  );

  const settingsRef = useRef(settings);
  const permissionRef = useRef(permission);
  const lastFiredAtRef = useRef<Map<string, number>>(new Map());
  const seenIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);
  useEffect(() => {
    permissionRef.current = permission;
  }, [permission]);

  function setSettings(next: NotificationSettings) {
    setSettingsState(next);
    saveNotificationSettings(next);
  }

  // This has to be an effect, not derived-during-render state: it's
  // synchronizing with an external stream (the WebSocket) and firing real
  // side effects (audio, browser Notifications) exactly once per signal,
  // not just computing a value from props.
  useEffect(() => {
    if (signals.length === 0) return;

    // `signals` is newest-first and only ever grows at the front, so the
    // first ids we've already seen mark where "new since last render" ends.
    const freshNewestFirst: SignalMessage[] = [];
    for (const signal of signals) {
      const id = signalId(signal);
      if (seenIdsRef.current.has(id)) break;
      seenIdsRef.current.add(id);
      freshNewestFirst.push(signal);
    }
    if (freshNewestFirst.length === 0) return;

    const settingsNow = settingsRef.current;
    const newToasts: ToastSignal[] = [];

    // Oldest-first so cooldowns/ordering read naturally if several arrived at once.
    for (const signal of freshNewestFirst.slice().reverse()) {
      if (!isRuleEnabled(settingsNow, signal.rule)) continue;

      const key = `${signal.ticker}:${signal.rule}`;
      const now = Date.now();
      const lastFiredAt = lastFiredAtRef.current.get(key) ?? 0;
      const cooldownMs = settingsNow.cooldownMinutes * 60_000;
      if (now - lastFiredAt < cooldownMs) continue;
      lastFiredAtRef.current.set(key, now);

      newToasts.push({ ...signal, id: signalId(signal) });

      if (!settingsNow.muted) {
        if (signal.direction === "long") playLongAlertTone();
        else playShortAlertTone();
      }

      if (permissionRef.current === "granted" && browserNotificationsSupported()) {
        try {
          new Notification(`${signal.ticker} — ${signal.rule.replace(/_/g, " ")}`, {
            body: `${signal.direction.toUpperCase()} @ ${signal.price}`,
            tag: key,
          });
        } catch {
          // Some environments (e.g. certain mobile browsers) throw from the
          // Notification constructor directly instead of just not firing.
        }
      }
    }

    if (newToasts.length > 0) {
      setToasts((prev) => [...newToasts.reverse(), ...prev].slice(0, 50));
    }
  }, [signals]);

  function dismissToast(id: string) {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }

  async function requestPermission() {
    if (!browserNotificationsSupported()) return;
    const result = await Notification.requestPermission();
    setPermission(result);
  }

  return {
    settings,
    setSettings,
    toasts,
    dismissToast,
    permission,
    requestPermission,
  };
}
