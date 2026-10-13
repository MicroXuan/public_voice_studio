import assert from "node:assert/strict";
import test from "node:test";

import {
  backoffDelay,
  filterVoices,
  formatApiError,
  groupLocales,
  loadFavorites,
  normalizeApiBase,
  toggleFavorite,
} from "../../frontend/lib.js";

const voices = [
  {
    short_name: "fr-FR-DeniseNeural",
    friendly_name: "Denise French",
    local_name: "Dénise",
    locale: "fr-FR",
    gender: "Female",
  },
  {
    short_name: "zh-CN-XiaoxiaoNeural",
    friendly_name: "Xiaoxiao Chinese",
    local_name: "晓晓",
    locale: "zh-CN",
    gender: "Female",
  },
  {
    short_name: "en-US-GuyNeural",
    friendly_name: "Guy English",
    local_name: "Guy",
    locale: "en-US",
    gender: "Male",
  },
];

test("normalizes absolute and relative API base URLs", () => {
  assert.equal(normalizeApiBase("https://api.example.com///"), "https://api.example.com");
  assert.equal(
    normalizeApiBase("/backend/", "https://voice.example.com/studio/"),
    "https://voice.example.com/backend",
  );
  assert.equal(normalizeApiBase("", "https://voice.example.com/page"), "https://voice.example.com");
  assert.throws(() => normalizeApiBase("javascript:alert(1)"), /HTTP/);
});

test("search is accent and case insensitive across names and locale", () => {
  assert.deepEqual(
    filterVoices(voices, { query: "DENISE" }).map((voice) => voice.short_name),
    ["fr-FR-DeniseNeural"],
  );
  assert.equal(filterVoices(voices, { query: "fr-fr" }).length, 1);
  assert.equal(filterVoices(voices, { query: "不存在" }).length, 0);
});

test("filters language region and gender while sorting favorites first stably", () => {
  const repeated = [voices[0], voices[1], voices[2], { ...voices[2], short_name: "en-GB-RyanNeural", locale: "en-GB" }];
  const result = filterVoices(repeated, {
    language: "en",
    gender: "Male",
    favorites: new Set(["en-GB-RyanNeural"]),
  });

  assert.deepEqual(result.map((voice) => voice.short_name), ["en-GB-RyanNeural", "en-US-GuyNeural"]);
  assert.deepEqual(
    filterVoices(repeated, { region: "US" }).map((voice) => voice.short_name),
    ["en-US-GuyNeural"],
  );
});

test("handles hundreds of voices, long names and empty results without mutation", () => {
  const many = Array.from({ length: 600 }, (_, index) => ({
    ...voices[index % voices.length],
    short_name: `voice-${index}-${"long-name-".repeat(20)}`,
  }));
  const snapshot = structuredClone(many);

  assert.equal(filterVoices(many, {}).length, 600);
  assert.deepEqual(filterVoices(many, { query: "no-match-at-all" }), []);
  assert.deepEqual(many, snapshot);
});

test("groups locale language and region with stable code fallback", () => {
  const grouped = groupLocales(voices, "zh-CN");

  assert.deepEqual(grouped.languages.map((item) => item.code), ["en", "fr", "zh"]);
  assert.deepEqual(grouped.regions.map((item) => item.code), ["CN", "FR", "US"]);
  assert.equal(grouped.languages.find((item) => item.code === "zh").count, 1);
  assert.ok(grouped.languages.every((item) => item.label));
});

test("favorites survive corrupt storage and toggle immutably", () => {
  const corrupt = { getItem: () => "{bad json" };
  const valid = { getItem: () => '["a","a",3,"b"]' };

  assert.deepEqual([...loadFavorites(corrupt)], []);
  assert.deepEqual([...loadFavorites(valid)], ["a", "b"]);
  const original = new Set(["a"]);
  const added = toggleFavorite(original, "b");
  const removed = toggleFavorite(added, "a");
  assert.deepEqual([...original], ["a"]);
  assert.deepEqual([...added], ["a", "b"]);
  assert.deepEqual([...removed], ["b"]);
});

test("formats stable API and network errors for people", () => {
  assert.equal(formatApiError({ error: { message: "队列已满" } }), "队列已满");
  assert.equal(formatApiError(null, 503), "服务正在唤醒或暂时繁忙，请稍后重试");
  assert.equal(formatApiError(new TypeError("Failed to fetch")), "暂时无法连接语音服务，请检查网络后重试");
  assert.equal(formatApiError({}, 500), "发生了意外错误，请稍后重试");
});

test("cold-start backoff grows exponentially and is capped", () => {
  assert.deepEqual(
    [0, 1, 2, 3, 4, 8].map((attempt) => backoffDelay(attempt, { base: 1_000, cap: 12_000 })),
    [1_000, 2_000, 4_000, 8_000, 12_000, 12_000],
  );
});
