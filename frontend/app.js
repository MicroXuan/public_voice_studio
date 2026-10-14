import {
  backoffDelay,
  filterVoices,
  filterVoicesByRegions,
  formatPlaybackTime,
  formatApiError,
  groupLocales,
  loadFavorites,
  normalizeApiBase,
  pickDefaultVoice,
  pickSelectValue,
  playbackPercent,
  replaceAudioSource,
  toggleFavorite,
  voiceDisplayName,
} from "./lib.js";

const config = window.XUAN_VOICE_CONFIG || {};
const apiBase = normalizeApiBase(config.apiBase || "", window.location.href);
const favoriteKey = "xiaoxuan-voice-studio:favorites";
const publicRegionCodes = ["US", "JP", "CN", "TW", "HK", "KR", "IN", "AR"];

const elements = {
  sourceText: document.querySelector("#source-text"),
  characterCount: document.querySelector("#character-count"),
  clearText: document.querySelector("#clear-text"),
  voiceSearch: document.querySelector("#voice-search"),
  language: document.querySelector("#language-filter"),
  region: document.querySelector("#region-filter"),
  gender: document.querySelector("#gender-filter"),
  favoritesOnly: document.querySelector("#favorites-only"),
  voiceList: document.querySelector("#voice-list"),
  voiceEmpty: document.querySelector("#voice-empty"),
  voiceCount: document.querySelector("#voice-count"),
  rate: document.querySelector("#rate-control"),
  pitch: document.querySelector("#pitch-control"),
  volume: document.querySelector("#volume-control"),
  rateValue: document.querySelector("#rate-value"),
  pitchValue: document.querySelector("#pitch-value"),
  volumeValue: document.querySelector("#volume-value"),
  resetControls: document.querySelector("#reset-controls"),
  generate: document.querySelector("#generate-button"),
  status: document.querySelector("#status-message"),
  resultState: document.querySelector("#result-state"),
  progressTrack: document.querySelector("#progress-track"),
  progressBar: document.querySelector("#progress-bar"),
  audioRegion: document.querySelector("#audio-region"),
  audio: document.querySelector("#audio-player"),
  audioToggle: document.querySelector("#audio-toggle"),
  audioSeek: document.querySelector("#audio-seek"),
  audioCurrentTime: document.querySelector("#audio-current-time"),
  audioDuration: document.querySelector("#audio-duration"),
  audioMute: document.querySelector("#audio-mute"),
  audioVolume: document.querySelector("#audio-volume"),
  download: document.querySelector("#download-audio"),
  resultCard: document.querySelector("#result-card"),
  turnstile: document.querySelector("#turnstile-container"),
  contactTrigger: document.querySelector("#contact-trigger"),
  contactDialog: document.querySelector("#wechat-dialog"),
  contactClose: document.querySelector("#contact-close"),
};

const state = {
  voices: [],
  selectedVoice: "",
  favorites: loadFavorites(window.localStorage, favoriteKey),
  pollController: null,
  pollSequence: 0,
  turnstileToken: null,
};

function setStatus(message, tone = "neutral") {
  elements.status.textContent = message;
  elements.status.classList.toggle("is-error", tone === "error");
  elements.status.classList.toggle("is-success", tone === "success");
}

function setProgress(value, visible = true) {
  const safe = Math.max(0, Math.min(100, Number(value) || 0));
  elements.progressTrack.hidden = !visible;
  elements.progressTrack.setAttribute("aria-valuenow", String(safe));
  elements.progressBar.style.width = `${safe}%`;
}

function updateCharacterCount() {
  const length = Array.from(elements.sourceText.value).length;
  elements.characterCount.textContent = `${length.toLocaleString("zh-CN")} / 5,000`;
  elements.characterCount.classList.toggle("is-limit", length >= 5_000);
}

function fillSelect(select, values, defaultLabel, preferredValue = "") {
  const current = select.value;
  select.replaceChildren(new Option(defaultLabel, ""));
  for (const item of values) {
    select.add(new Option(item.label, item.code));
  }
  select.value = pickSelectValue(values, current, preferredValue);
}

function renderFilters() {
  const groups = groupLocales(state.voices, "zh-CN");
  fillSelect(elements.language, groups.languages, "全部语言");
  fillSelect(elements.region, groups.regions, "全部地区", "CN");
}

function voiceGlyph() {
  const wrapper = document.createElement("span");
  wrapper.className = "voice-glyph";
  wrapper.setAttribute("aria-hidden", "true");
  wrapper.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 12v3m4-7v8m4-12v16m4-10v5m4-3v1" /></svg>';
  return wrapper;
}

function favoriteIcon() {
  const template = document.createElement("template");
  template.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z" /></svg>';
  return template.content.firstElementChild;
}

function renderVoiceList() {
  const filtered = filterVoices(state.voices, {
    query: elements.voiceSearch.value,
    language: elements.language.value,
    region: elements.region.value,
    gender: elements.gender.value,
    favorites: state.favorites,
  }).filter((voice) => !elements.favoritesOnly.checked || state.favorites.has(voice.short_name));

  elements.voiceList.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const voice of filtered) {
    const option = document.createElement("div");
    option.className = "voice-option";
    option.dataset.voice = voice.short_name;
    option.setAttribute("role", "option");
    option.setAttribute("tabindex", "0");
    option.setAttribute("aria-selected", String(voice.short_name === state.selectedVoice));

    const copy = document.createElement("span");
    copy.className = "voice-copy";
    const name = document.createElement("strong");
    const displayName = voiceDisplayName(voice);
    name.textContent = displayName;
    const details = document.createElement("small");
    const romanizedName = voice.local_name && voice.local_name !== displayName ? `${voice.local_name} · ` : "";
    details.textContent = `${romanizedName}${voice.locale} · ${voice.gender === "Female" ? "女声" : voice.gender === "Male" ? "男声" : voice.gender}`;
    copy.append(name, details);

    const favorite = document.createElement("button");
    favorite.type = "button";
    favorite.className = `favorite-button${state.favorites.has(voice.short_name) ? " is-favorite" : ""}`;
    favorite.dataset.favorite = voice.short_name;
    favorite.setAttribute("aria-label", `${state.favorites.has(voice.short_name) ? "取消收藏" : "收藏"}${displayName}`);
    favorite.append(favoriteIcon());
    option.append(voiceGlyph(), copy, favorite);
    fragment.append(option);
  }
  elements.voiceList.append(fragment);
  elements.voiceList.setAttribute("aria-busy", "false");
  elements.voiceCount.textContent = `${filtered.length} / ${state.voices.length} 个声音`;
  elements.voiceEmpty.hidden = filtered.length !== 0;
}

function showVoiceSkeletons() {
  elements.voiceList.replaceChildren();
  for (let index = 0; index < 6; index += 1) {
    const skeleton = document.createElement("div");
    skeleton.className = "voice-skeleton";
    skeleton.setAttribute("aria-hidden", "true");
    elements.voiceList.append(skeleton);
  }
}

function sleep(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

async function responseJson(response) {
  try { return await response.json(); }
  catch { return null; }
}

async function loadVoices() {
  showVoiceSkeletons();
  elements.voiceCount.textContent = "正在连接服务";
  const controller = new AbortController();

  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      const response = await fetch(`${apiBase}/api/voices`, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      const data = await responseJson(response);
      if (!response.ok) {
        if (response.status === 503 && attempt < 5) {
          setStatus("语音服务正在唤醒，页面无需刷新，连接后会自动继续。", "neutral");
          await sleep(backoffDelay(attempt, { base: 1_500, cap: 12_000 }), controller.signal);
          continue;
        }
        throw Object.assign(new Error("voice catalog"), { payload: data, status: response.status });
      }
      state.voices = filterVoicesByRegions(
        Array.isArray(data?.voices) ? data.voices : [],
        publicRegionCodes,
      );
      state.selectedVoice = pickDefaultVoice(state.voices, state.selectedVoice);
      renderFilters();
      renderVoiceList();
      setStatus("语音目录已就绪。输入文本后即可开始生成。", "neutral");
      return;
    } catch (error) {
      if (error.name === "AbortError") return;
      if (error instanceof TypeError && attempt < 5) {
        setStatus("语音服务正在唤醒，页面无需刷新，连接后会自动继续。", "neutral");
        await sleep(backoffDelay(attempt, { base: 1_500, cap: 12_000 }), controller.signal);
        continue;
      }
      const payload = error.payload || error;
      elements.voiceList.replaceChildren();
      elements.voiceCount.textContent = "载入失败";
      setStatus(formatApiError(payload, error.status), "error");
      return;
    }
  }
}

function selectVoice(shortName) {
  if (!state.voices.some((voice) => voice.short_name === shortName)) return;
  state.selectedVoice = shortName;
  renderVoiceList();
}

function persistFavorites() {
  window.localStorage.setItem(favoriteKey, JSON.stringify([...state.favorites]));
}

function updateControlOutput(input, output, suffix) {
  const value = Number(input.value);
  output.textContent = `${value > 0 ? "+" : ""}${value}${suffix}`;
}

function updateAudioTimeline() {
  const hasSource = elements.audio.hasAttribute("src");
  const duration = Number.isFinite(elements.audio.duration) ? elements.audio.duration : 0;
  const currentTime = duration > 0
    ? Math.max(0, Math.min(duration, elements.audio.currentTime || 0))
    : 0;
  const playing = hasSource && !elements.audio.paused && !elements.audio.ended;
  elements.audioToggle.disabled = !hasSource;
  elements.audioToggle.dataset.playing = String(playing);
  elements.audioToggle.setAttribute("aria-label", playing ? "暂停" : "播放");
  elements.audioSeek.disabled = duration <= 0;
  elements.audioSeek.max = String(duration);
  elements.audioSeek.value = String(currentTime);
  elements.audioSeek.style.setProperty(
    "--audio-range-progress",
    `${playbackPercent(currentTime, duration)}%`,
  );
  elements.audioCurrentTime.textContent = formatPlaybackTime(currentTime);
  elements.audioDuration.textContent = formatPlaybackTime(duration);
}

function updateAudioVolume() {
  const volume = elements.audio.muted ? 0 : elements.audio.volume;
  elements.audioMute.setAttribute("aria-pressed", String(elements.audio.muted || volume === 0));
  elements.audioMute.setAttribute("aria-label", elements.audio.muted || volume === 0 ? "取消静音" : "静音");
  elements.audioVolume.value = String(volume);
  elements.audioVolume.style.setProperty("--audio-range-progress", `${volume * 100}%`);
}

function resetResult() {
  replaceAudioSource(elements.audio);
  updateAudioTimeline();
  elements.audioRegion.hidden = true;
  setProgress(0, false);
  elements.resultState.textContent = "等待生成";
}

function absoluteApiUrl(path) {
  return new URL(path, `${apiBase}/`).href;
}

function revealResult() {
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  elements.resultCard.scrollIntoView({
    behavior: reducedMotion ? "auto" : "smooth",
    block: "nearest",
  });
}

async function pollJob(location, sequence, signal) {
  let attempt = 0;
  while (!signal.aborted && sequence === state.pollSequence) {
    const response = await fetch(absoluteApiUrl(location), {
      headers: { Accept: "application/json" },
      signal,
    });
    const data = await responseJson(response);
    if (!response.ok) throw Object.assign(new Error("poll failed"), { payload: data, status: response.status });

    elements.resultState.textContent = data.state === "queued" ? "排队中" : data.state === "running" ? "生成中" : "处理中";
    setStatus(data.message || "正在生成语音");
    setProgress(data.progress ?? 0, true);

    if (data.state === "completed") {
      const audioUrl = absoluteApiUrl(data.audio_url);
      replaceAudioSource(elements.audio, audioUrl);
      updateAudioTimeline();
      elements.download.href = absoluteApiUrl(data.download_url || `${data.audio_url}?download=1`);
      elements.audioRegion.hidden = false;
      elements.resultState.textContent = "已完成";
      setProgress(100, true);
      setStatus("语音已生成，可以试听或下载 MP3。", "success");
      window.requestAnimationFrame(revealResult);
      return;
    }
    if (["failed", "expired"].includes(data.state)) {
      throw Object.assign(new Error("job failed"), { payload: { error: { message: data.message } }, status: 409 });
    }
    await sleep(backoffDelay(attempt, { base: 700, cap: 3_000 }), signal);
    attempt += 1;
  }
}

async function generateVoice() {
  const text = elements.sourceText.value.trim();
  if (!text) {
    setStatus("先输入需要朗读的文本。", "error");
    elements.sourceText.focus();
    return;
  }
  if (!state.selectedVoice) {
    setStatus("语音目录尚未就绪，请稍候。", "error");
    return;
  }

  state.pollController?.abort();
  state.pollController = new AbortController();
  const sequence = ++state.pollSequence;
  resetResult();
  elements.generate.disabled = true;
  elements.generate.querySelector("span").textContent = "正在提交…";
  elements.resultState.textContent = "连接中";
  setStatus("正在连接语音服务。免费实例唤醒时可能需要约 1 分钟。");
  setProgress(2, true);
  window.requestAnimationFrame(revealResult);

  try {
    const response = await fetch(`${apiBase}/api/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        text,
        voice: state.selectedVoice,
        rate: Number(elements.rate.value),
        pitch: Number(elements.pitch.value),
        volume: Number(elements.volume.value),
        turnstile_token: state.turnstileToken,
      }),
      signal: state.pollController.signal,
    });
    const data = await responseJson(response);
    if (!response.ok) throw Object.assign(new Error("submission failed"), { payload: data, status: response.status });
    const location = response.headers.get("Location") || `/api/jobs/${data.id}`;
    await pollJob(location, sequence, state.pollController.signal);
  } catch (error) {
    if (error.name !== "AbortError" && sequence === state.pollSequence) {
      elements.resultState.textContent = "未完成";
      setProgress(0, false);
      setStatus(formatApiError(error.payload || error, error.status), "error");
    }
  } finally {
    if (sequence === state.pollSequence) {
      elements.generate.disabled = false;
      elements.generate.querySelector("span").textContent = "生成语音";
      if (window.turnstile && config.turnstileSiteKey) {
        window.turnstile.reset();
        state.turnstileToken = null;
      }
    }
  }
}

function setupTurnstile() {
  if (!config.turnstileSiteKey) return;
  elements.turnstile.hidden = false;
  const script = document.createElement("script");
  script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  script.async = true;
  script.defer = true;
  script.addEventListener("load", () => {
    window.turnstile.render(elements.turnstile, {
      sitekey: config.turnstileSiteKey,
      callback: (token) => { state.turnstileToken = token; },
      "expired-callback": () => { state.turnstileToken = null; },
    });
  });
  document.head.append(script);
}

function openContactDialog() {
  elements.contactDialog.showModal();
  document.body.classList.add("has-open-dialog");
}

function closeContactDialog() {
  elements.contactDialog.close();
}

elements.sourceText.addEventListener("input", updateCharacterCount);
elements.clearText.addEventListener("click", () => {
  elements.sourceText.value = "";
  updateCharacterCount();
  elements.sourceText.focus();
});
[elements.voiceSearch, elements.language, elements.region, elements.gender, elements.favoritesOnly].forEach((control) => {
  control.addEventListener(control === elements.voiceSearch ? "input" : "change", renderVoiceList);
});
elements.voiceList.addEventListener("click", (event) => {
  const favorite = event.target.closest("[data-favorite]");
  if (favorite) {
    state.favorites = toggleFavorite(state.favorites, favorite.dataset.favorite);
    persistFavorites();
    renderVoiceList();
    return;
  }
  const option = event.target.closest("[data-voice]");
  if (option) selectVoice(option.dataset.voice);
});
elements.voiceList.addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-voice]")) {
    event.preventDefault();
    selectVoice(event.target.dataset.voice);
  }
});
[
  [elements.rate, elements.rateValue, "%"],
  [elements.pitch, elements.pitchValue, " Hz"],
  [elements.volume, elements.volumeValue, "%"],
].forEach(([input, output, suffix]) => input.addEventListener("input", () => updateControlOutput(input, output, suffix)));
elements.resetControls.addEventListener("click", () => {
  for (const [input, output, suffix] of [
    [elements.rate, elements.rateValue, "%"],
    [elements.pitch, elements.pitchValue, " Hz"],
    [elements.volume, elements.volumeValue, "%"],
  ]) {
    input.value = "0";
    updateControlOutput(input, output, suffix);
  }
});
elements.generate.addEventListener("click", generateVoice);
elements.audioToggle.addEventListener("click", async () => {
  if (!elements.audio.hasAttribute("src")) return;
  if (!elements.audio.paused && !elements.audio.ended) {
    elements.audio.pause();
    return;
  }
  if (elements.audio.ended) elements.audio.currentTime = 0;
  try {
    await elements.audio.play();
  } catch {
    setStatus("音频暂时无法播放，请重试或下载 MP3。", "error");
  }
});
elements.audioSeek.addEventListener("input", () => {
  const nextTime = Number(elements.audioSeek.value);
  if (Number.isFinite(elements.audio.duration) && Number.isFinite(nextTime)) {
    elements.audio.currentTime = Math.max(0, Math.min(elements.audio.duration, nextTime));
    updateAudioTimeline();
  }
});
elements.audioMute.addEventListener("click", () => {
  elements.audio.muted = !elements.audio.muted;
});
elements.audioVolume.addEventListener("input", () => {
  const volume = Math.max(0, Math.min(1, Number(elements.audioVolume.value) || 0));
  elements.audio.volume = volume;
  elements.audio.muted = volume === 0;
});
["loadedmetadata", "durationchange", "timeupdate", "play", "pause", "ended", "emptied"].forEach((eventName) => {
  elements.audio.addEventListener(eventName, updateAudioTimeline);
});
elements.audio.addEventListener("volumechange", updateAudioVolume);
elements.contactTrigger.addEventListener("click", openContactDialog);
elements.contactClose.addEventListener("click", closeContactDialog);
elements.contactDialog.addEventListener("click", (event) => {
  if (event.target === elements.contactDialog) closeContactDialog();
});
elements.contactDialog.addEventListener("close", () => {
  document.body.classList.remove("has-open-dialog");
  elements.contactTrigger.focus();
});

updateCharacterCount();
updateAudioTimeline();
updateAudioVolume();
setupTurnstile();
loadVoices();
