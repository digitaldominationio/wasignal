export function timeAgo(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "—";
  const seconds = Math.max(1, Math.floor(Date.now() / 1000 - epochSeconds));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString();
}

export function clockTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function dayKey(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

export function dayLabel(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000);
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);

  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

  if (sameDay(date, now)) return "Today";
  if (sameDay(date, yesterday)) return "Yesterday";
  return date.toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
}

export function dateTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .replace(/[^\p{L}\p{N} ]/gu, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function inr(amount: number): string {
  return `₹${amount.toLocaleString("en-IN")}`;
}
