import type { SessionTimeoutResponse } from "./api";

/** Build deployment-specific choices while retaining the stored preference. */
export function sessionTimeoutOptions(timeout: SessionTimeoutResponse | null) {
  if (!timeout) return [];
  const presets = timeout.presets.filter(
    (minutes) => minutes >= timeout.min_minutes && minutes <= timeout.max_minutes,
  );
  // A custom range may contain none of the standard presets.
  if (presets.length === 0) presets.push(timeout.min_minutes);
  return [...new Set([...presets, timeout.minutes])]
    .sort((a, b) => a - b)
    .map((value) => ({ value, label: formatSessionTimeout(value) }));
}

/** Format a session duration, including values outside the standard presets. */
export function formatSessionTimeout(minutes: number): string {
  if (minutes > 1440 && minutes % 1440 === 0) return `${minutes / 1440} days`;
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return `${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
}
