/** Small inline marker for a section heading whose contents may be frozen
 * — paired with dimming the section itself. See StaleDataBanner for the
 * page-level version of the same signal. */
export function StaleBadge() {
  return (
    <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold uppercase text-amber-400">
      Stale
    </span>
  );
}
