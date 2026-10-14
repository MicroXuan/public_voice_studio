const FAVORITES_KEY = "xiaoxuan-voice-studio:favorites";

const CHINESE_VOICE_NAMES = Object.freeze({
  "zh-CN-XiaoxiaoNeural": "晓晓",
  "zh-CN-XiaoyiNeural": "晓伊",
  "zh-CN-YunjianNeural": "云健",
  "zh-CN-YunxiNeural": "云希",
  "zh-CN-YunxiaNeural": "云夏",
  "zh-CN-YunyangNeural": "云扬",
  "zh-CN-liaoning-XiaobeiNeural": "晓北",
  "zh-CN-shaanxi-XiaoniNeural": "晓妮",
  "zh-HK-HiuGaaiNeural": "曉佳",
  "zh-HK-HiuMaanNeural": "曉曼",
  "zh-HK-WanLungNeural": "雲龍",
  "zh-TW-HsiaoChenNeural": "曉臻",
  "zh-TW-HsiaoYuNeural": "曉雨",
  "zh-TW-YunJheNeural": "雲哲",
});

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

export function voiceDisplayName(voice) {
  return CHINESE_VOICE_NAMES[voice?.short_name] || voice?.local_name || voice?.short_name || "";
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
        voiceDisplayName(voice),
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

export function filterVoicesByRegions(voices, allowedRegions) {
  const allowed = new Set(
    [...(allowedRegions || [])]
      .map((region) => String(region).toUpperCase())
      .filter(Boolean),
  );
  return voices.filter((voice) => allowed.has(localeParts(voice.locale).region));
}

export function pickDefaultVoice(voices, current, preferred = "zh-CN-XiaoxiaoNeural") {
  if (voices.some((voice) => voice.short_name === current)) return current;
  if (voices.some((voice) => voice.short_name === preferred)) return preferred;
  return voices[0]?.short_name || "";
}

export function pickSelectValue(values, current, preferred = "") {
  if (values.some((item) => item.code === current)) return current;
  if (values.some((item) => item.code === preferred)) return preferred;
  return "";
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

export function replaceAudioSource(audio, source = "") {
  audio.pause();
  audio.removeAttribute("src");
  if (source) audio.src = source;
  audio.load();
}

export function formatPlaybackTime(value) {
  const totalSeconds = Number.isFinite(Number(value))
    ? Math.max(0, Math.floor(Number(value)))
    : 0;
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function playbackPercent(currentTime, duration) {
  const current = Number(currentTime);
  const total = Number(duration);
  if (!Number.isFinite(current) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, Math.min(100, (current / total) * 100));
}
