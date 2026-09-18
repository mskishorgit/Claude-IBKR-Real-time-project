/** Synthesized (no asset files, no network) audible alerts, distinct for
 * long vs short signals. Uses the Web Audio API directly rather than
 * <audio> files since a couple of oscillator tones need no assets to ship
 * or host. */

let audioContext: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  try {
    if (!audioContext) {
      audioContext = new Ctor();
    }
    if (audioContext.state === "suspended") {
      void audioContext.resume();
    }
    return audioContext;
  } catch {
    return null;
  }
}

function playTones(frequencies: number[], durationEach = 0.12): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  let startAt = ctx.currentTime;
  for (const frequency of frequencies) {
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;

    // Quick fade in/out avoids an audible click at the start/end of each tone.
    gain.gain.setValueAtTime(0.0001, startAt);
    gain.gain.exponentialRampToValueAtTime(0.2, startAt + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, startAt + durationEach);

    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start(startAt);
    oscillator.stop(startAt + durationEach + 0.02);

    startAt += durationEach;
  }
}

/** Ascending two-note chime for a long/bullish signal. */
export function playLongAlertTone(): void {
  playTones([660, 880]);
}

/** Descending two-note chime for a short/bearish signal. */
export function playShortAlertTone(): void {
  playTones([660, 440]);
}

/** Unlocks the AudioContext from a real user gesture (autoplay policies
 * block audio until one occurs) and plays a quick confirmation tone —
 * wired to the settings panel's "Test sound" button. */
export function playTestAlertTone(): void {
  playTones([660, 880, 660]);
}
