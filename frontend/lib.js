const FAVORITES_KEY = "xiaoxuan-voice-studio:favorites";

function pageBase(fallback) {
  if (fallback) return fallback;
  if (typeof window !== "undefined" && window.location) return window.location.href;
  return "http://localhost:5173/";
}

export function normalizeApiBase(value, pageUrl) {
  const base = new URL(pageBase(pageUrl));
  const candidate = value && String(value).trim() ? new URL(String(value).trim(), base) : new URL(base.origin);
  if (!['http:', 'https:'].includes(candidate.protocol)) {
    throw new TypeError("API base must use HTTP or HTTPS");
  }
  const normalizedPath = candidate.pathname.replace(/\/+$/, "");
  return `${candidate.origin}${normalizedPath}`;
}

function fold(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase();
}

function localeParts(locale) {
  try {
    const parsed = new Intl.Locale(locale);
    return { language: parsed.language, region: parsed.region || "" };
  } catch {
    const parts = String(locale).split("-");
    return {
      language: (parts[0] || "").toLowerCase(),
      region: (parts.find((part) => /^[A-Za-z]{2}$/.test(part) && part !== parts[0]) || "").toUpperCase(),
    };
  }
}

export function filterVoices(voices, filters = {}) {
  const query = fold(filters.query).trim();
  const language = String(filters.language || "").toLowerCase();
  const region = String(filters.region || "").toUpperCase();
  const gender = fold(filters.gender);
  const favorites = filters.favorites instanceof Set ? filters.favorites : new Set(filters.favorites || []);

  return voices
    .map((voice, index) => ({ voice, index }))
    .filter(({ voice }) => {
      const parts = localeParts(voice.locale);
      const searchable = fold([
        voice.short_name,
        voice.friendly_name,
        voice.local_name,
        voice.locale,
        voice.gender,
      ].join(" "));
      return (
        (!query || searchable.includes(query)) &&
        (!language || parts.language === language) &&
        (!region || parts.region === region) &&
        (!gender || fold(voice.gender) === gender)
      );
    })
    .sort((left, right) => {
      const favoriteOrder = Number(favorites.has(right.voice.short_name)) - Number(favorites.has(left.voice.short_name));
      return favoriteOrder || left.index - right.index;
    })
    .map(({ voice }) => voice);
}

function displayName(type, code, displayLocale) {
  try {
    return new Intl.DisplayNames([displayLocale], { type }).of(code) || code;
  } catch {
    return code;
  }
}

export function groupLocales(voices, displayLocale = "zh-CN") {
  const languageCounts = new Map();
  const regionCounts = new Map();
  for (const voice of voices) {
    const { language, region } = localeParts(voice.locale);
    if (language) languageCounts.set(language, (languageCounts.get(language) || 0) + 1);
    if (region) regionCounts.set(region, (regionCounts.get(region) || 0) + 1);
  }
  return {
    languages: [...languageCounts]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([code, count]) => ({ code, count, label: displayName("language", code, displayLocale) })),
    regions: [...regionCounts]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([code, count]) => ({ code, count, label: displayName("region", code, displayLocale) })),
  };
}

export function loadFavorites(storage, key = FAVORITES_KEY) {
  try {
    const parsed = JSON.parse(storage?.getItem(key) || "[]");
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((value) => typeof value === "string" && value));
  } catch {
    return new Set();
  }
}

export function toggleFavorite(favorites, shortName) {
  const next = new Set(favorites);
  if (next.has(shortName)) next.delete(shortName);
  else next.add(shortName);
  return next;
}

export function formatApiError(value, status = 0) {
  if (value instanceof TypeError) {
    return "暂时无法连接语音服务，请检查网络后重试";
  }
  const message = value?.error?.message;
  if (typeof message === "string" && message.trim()) return message.trim();
  if (status === 503 || status === 502 || status === 504) {
    return "服务正在唤醒或暂时繁忙，请稍后重试";
  }
  return "发生了意外错误，请稍后重试";
}

export function backoffDelay(attempt, { base = 1_000, cap = 15_000 } = {}) {
  const exponent = Math.max(0, Math.floor(Number(attempt) || 0));
  return Math.min(cap, base * 2 ** exponent);
}
