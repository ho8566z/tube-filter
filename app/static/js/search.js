"use strict";

// Export the form mapping separately so it can be exercised with a mock DOM.
window.tubeSearch = (() => {
  const videoRanges = ["durationSec", "views", "likes", "comments", "likeRatePct", "commentRatePct"];
  const channelRanges = ["subscribers", "viewsPerSubPct", "videoCount", "avgViews"];
  const validVideoId = id => typeof id === "string" && id.length === 11 && /^[A-Za-z0-9_-]{11}$/.test(id);
  const embedUrl = id => validVideoId(id) ? `https://www.youtube-nocookie.com/embed/${id}` : null;
  const duration = value => {
    if (!/^\d+:[0-5]\d$/.test(value)) throw new Error("mm:ss 형식으로 입력하세요. 예: 07:03");
    const [minutes, seconds] = value.split(":").map(Number);
    return minutes * 60 + seconds;
  };
  function formBody(form) {
    const controls = Array.from(form.elements);
    const get = name => controls.find(c => c.name === name)?.value ?? "";
    const checked = name => controls.some(c => c.name === name && c.checked);
    const multiple = name => Array.from(controls.find(c => c.name === name)?.selectedOptions || [], o => o.value);
    const object = (names, prefix, numeric = false) => Object.fromEntries(names
      .filter(k => get(`${prefix}.${k}`) !== "")
      .map(k => [k, numeric ? Number(get(`${prefix}.${k}`)) : get(`${prefix}.${k}`)]));
    const bounds = (prefix, isDuration = false) => {
      const b = object(["min", "max"], prefix, !isDuration);
      if (isDuration) for (const k of Object.keys(b)) b[k] = duration(b[k]);
      return b;
    };
    const tokens = name => {
      const field = Array.from(form.querySelectorAll("[data-chips]")).find(f => f.dataset.chips === name);
      const pending = field?.querySelector("[data-chip-input]")?.value.trim().toLowerCase();
      const values = Array.from(field?.querySelectorAll("[data-token]") || [], c => c.dataset.token);
      return [...new Set([...values, ...(pending ? [pending] : [])])];
    };
    const video = Object.fromEntries(videoRanges.map(k => [k, bounds(`video.${k}`, k === "durationSec")]));
    Object.assign(video, {
      tags: {include: tokens("video.tags.include"), exclude: tokens("video.tags.exclude"), mode: get("video.tags.mode")},
      words: {must: tokens("video.words.must"), not: tokens("video.words.not"), target: get("video.words.target")},
      categoryIds: {include: multiple("video.categoryIds.include").map(Number), exclude: multiple("video.categoryIds.exclude").map(Number)},
      languages: multiple("video.languages"),
      weekdays: controls.filter(c => c.name === "video.weekdays" && c.checked).map(c => Number(c.value)),
      hours: object(["from", "to"], "video.hours", true),
      shorts: controls.find(c => c.name === "video.shorts" && c.checked)?.value || "ANY",
      regionCode: get("video.regionCode") || "KR", relevanceLanguage: get("video.relevanceLanguage") || null,
      excludeRestricted: checked("restrictEnabled") || checked("anyRestriction") ? {
        country: get("restrictedCountry") || "KR", anyRestriction: checked("anyRestriction"),
      } : {},
    });
    for (const k of ["includeNoLanguage", "excludeKids", "hd", "caption", "cc", "embeddable"]) video[k] = checked(`video.${k}`);
    const channel = Object.fromEntries(channelRanges.map(k => [k, bounds(`channel.${k}`)]));
    channel.countries = multiple("channel.countries").map(v => v === "__unset__" ? null : v);
    channel.created = get("createdMode") === "withinDays" && get("createdDays") !== "" ? {withinDays: Number(get("createdDays"))}
      : get("createdMode") === "before" && get("createdBefore") ? {before: get("createdBefore")} : {};
    channel.activity = object(["countMin", "countMax", "lastUploadWithinDays"], "channel.activity", true);
    if (Object.keys(channel.activity).length) channel.activity.windowDays = Number(get("channel.activity.windowDays"));
    return {keyword: get("keyword").trim(), pages: Number(get("pages")), order: get("order"), published: object(["after", "before"], "published"), video, channel};
  }
  const $ = id => document.getElementById(id);
  const api = (path, options) => window.tubeFilter.api(path, options);
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const number = n => n == null ? "비공개" : Number(n).toLocaleString("ko-KR", {maximumFractionDigits: 2});
  const date = value => value && !Number.isNaN(Date.parse(value)) ? new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short", hourCycle: "h23",
  }).format(new Date(value)) + " (KST)" : "비공개";
  const minute = n => n == null ? "비공개" : `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
  let favoriteSnapshot;
  const favoriteStates = new Map();
  async function favoriteIds() {
    if (!favoriteSnapshot) favoriteSnapshot = (async () => {
      for (let page = 0; ; page++) {
        const result = await api(`/api/v1/favorites?page=${page}&size=50`);
        result.items.forEach(item => { if (!favoriteStates.has(item.videoId)) favoriteStates.set(item.videoId, true); });
        if (page + 1 >= result.totalPages) break;
      }
    })().catch(error => { favoriteSnapshot = null; throw error; });
    await favoriteSnapshot;
  }
  function favoriteButton(videoId, saved = null, removed) {
    const button = node("button"); button.type = "button";
    if (saved !== null) favoriteStates.set(videoId, saved);
    const paint = () => { button.textContent = saved ? "★ 즐겨찾기 해제" : "☆ 즐겨찾기"; button.setAttribute("aria-pressed", String(Boolean(saved))); };
    paint();
    if (saved === null && document.body?.dataset.member === "true") {
      button.disabled = true;
      favoriteIds().then(() => { saved = favoriteStates.get(videoId) || false; paint(); })
        .catch(error => { $("global-message").textContent = error.message; })
        .finally(() => { button.disabled = false; });
    }
    button.addEventListener("click", async () => {
      if (document.body.dataset.member !== "true") {
        $("global-message").replaceChildren(node("span", "로그인 후 이용할 수 있습니다. "));
        const link = node("a", "로그인"); link.href = "/login"; $("global-message").append(link); return;
      }
      button.disabled = true;
      try {
        if (saved === null) { await favoriteIds(); saved = favoriteStates.get(videoId) || false; }
        await api(`/api/v1/favorites/${encodeURIComponent(videoId)}`, {method: saved ? "DELETE" : "PUT"});
        saved = !saved; favoriteStates.set(videoId, saved); paint(); if (!saved) await removed?.();
      } catch (error) { if (error.status === 401) window.location.assign("/login"); else $("global-message").textContent = error.message; }
      finally { button.disabled = false; }
    });
    return button;
  }
  function openPlayer(item) {
    const url = window.tubeSearch.embedUrl(item.videoId);
    if (!url) { $("search-error").textContent = "영상 ID 형식이 올바르지 않습니다."; return; }
    $("player-container").replaceChildren();
    $("player-title").textContent = item.title || "영상 재생";
    $("player-link").href = `https://www.youtube.com/watch?v=${item.videoId}`;
    $("player-message").textContent = "재생할 수 없는 경우 YouTube에서 보기를 이용하세요.";
    if (item.embeddable !== false) {
      const frame = node("iframe"); frame.src = url; frame.title = item.title || "YouTube 영상 재생";
      frame.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
      frame.allowFullscreen = true; frame.referrerPolicy = "strict-origin-when-cross-origin";
      $("player-container").append(frame);
    } else $("player-message").textContent = "임베드할 수 없는 영상입니다. YouTube에서 확인하세요.";
    $("player-modal").showModal();
  }
  $("close-player")?.addEventListener("click", () => { $("player-container").replaceChildren(); $("player-modal").close(); });
  $("player-modal")?.addEventListener("close", () => $("player-container").replaceChildren());
  $("player-modal")?.addEventListener("cancel", () => $("player-container").replaceChildren());
  function videoCard(item, saved = null, removed) {
    if (item.available === false) {
      const card = node("article", undefined, "video-card");
      card.append(node("h3", item.title || "영상 정보를 불러오지 못했습니다."), favoriteButton(item.videoId, true, removed));
      return card;
    }
    const card = node("article", undefined, "video-card");
    if (window.tubeSearch.validVideoId(item.videoId)) card.id = `video-${item.videoId}`;
    card.tabIndex = -1;
    if (item.thumbnailUrl) {
      try { const url = new URL(item.thumbnailUrl); if (url.protocol === "https:" && ["i.ytimg.com", "img.youtube.com"].includes(url.hostname)) { const img = node("img"); img.src = url.href; img.alt = ""; img.loading = "lazy"; card.append(img); } } catch { /* Ignore invalid thumbnail URLs. */ }
    }
    card.append(node("h3", item.title || "제목 없음"));
    const channel = node("a", item.channelTitle || "비공개");
    if (item.channelId) channel.href = `/channels/${encodeURIComponent(item.channelId)}`;
    card.append(channel);
    card.append(node("p", `게시일 ${date(item.publishedAt)} · 길이 ${minute(item.durationSec)}`));
    const dl = node("dl");
    for (const [label, value, calc] of [["조회수",item.stats.views], ["좋아요",item.stats.likes], ["댓글",item.stats.comments], ["구독자",item.channel.subscribers], ["좋아요율 (%)",item.calc.likeRatePct,true], ["댓글 참여율 (%)",item.calc.commentRatePct,true], ["구독자 대비 조회수 (%)",item.calc.viewsPerSubPct,true]]) {
      const group = node("div"), dt = node("dt", label);
      if (calc) dt.append(node("span", "계산값 · YouTube 제공 지표가 아님", "badge"));
      group.append(dt, node("dd", number(value))); dl.append(group);
    }
    card.append(dl);
    const actions = node("div", undefined, "actions");
    if (window.tubeSearch.validVideoId(item.videoId)) {
      if (item.embeddable !== false) { const play = node("button", "재생"); play.type = "button"; play.addEventListener("click", () => openPlayer(item)); actions.append(play); }
      const link = node("a", "YouTube에서 보기"); link.href = `https://www.youtube.com/watch?v=${item.videoId}`; link.target = "_blank"; link.rel = "noopener noreferrer"; actions.append(link);
    }
    actions.append(favoriteButton(item.videoId, saved, removed)); card.append(actions);
    return card;
  }
  function applyConditions(form, data, chip) {
    const keyword = form.elements.namedItem("keyword").value;
    form.reset();
    form.elements.namedItem("keyword").value = data.keyword ?? keyword;
    const get = name => name.split(".").reduce((value, key) => value?.[key], data);
    const day = value => value ? new Intl.DateTimeFormat("sv-SE", {timeZone:"Asia/Seoul", year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(value)) : "";
    for (const el of Array.from(form.elements)) {
      if (!el.name || el.name === "keyword" || el.name.startsWith("result")) continue;
      const value = get(el.name);
      if (el.type === "checkbox" || el.type === "radio") el.checked = Array.isArray(value) ? value.includes(Number(el.value)) : el.type === "radio" ? value === el.value : Boolean(value);
      else if (el.multiple) for (const option of el.options) option.selected = (value || []).map(v => String(v ?? "__unset__")).includes(option.value);
      else if (value != null && typeof value !== "object") el.value = el.type === "date" ? day(value) : el.name.startsWith("video.durationSec.") ? minute(value) : String(value);
      else if (el.tagName === "INPUT") el.value = "";
    }
    const set = (name, value) => { const el = form.elements.namedItem(name); if (el) el.value = value ?? ""; };
    const created = data.channel?.created || {}, restricted = data.video?.excludeRestricted || {};
    set("createdMode", created.withinDays != null ? "withinDays" : created.before ? "before" : "");
    set("createdDays", created.withinDays); set("createdBefore", day(created.before));
    form.elements.namedItem("restrictEnabled").checked = Boolean(restricted.country);
    form.elements.namedItem("anyRestriction").checked = Boolean(restricted.anyRestriction);
    set("restrictedCountry", restricted.country || "KR");
    for (const field of form.querySelectorAll("[data-chips]")) {
      field.querySelector(".chips").replaceChildren();
      const input = field.querySelector("[data-chip-input]"); input.value = "";
      for (const value of get(field.dataset.chips) || []) { input.value = value; chip(field); }
    }
    for (const slider of form.querySelectorAll("[data-sync]")) {
      const value = get(slider.dataset.sync);
      slider.value = value == null ? slider.defaultValue : String(Math.min(Number(slider.max), value));
    }
    for (const input of form.querySelectorAll("[data-count]")) input.dispatchEvent(new Event("input", {bubbles:true}));
  }
  return {formBody, duration, validVideoId, embedUrl, videoRanges, channelRanges, videoCard, node, date, number, minute, applyConditions};
})();

(() => {
  const form = document.getElementById("search-form");
  if (!form) return;
  const $ = id => document.getElementById(id);
  const control = name => form.elements.namedItem(name);
  const api = (path, options) => window.tubeFilter.api(path, options);
  const {node, number, date, minute} = window.tubeSearch;
  let searchId = null, currentPage = null, busy = false, pageVersion = 0, analysisVersion = 0;
  let estimateTimer, estimateVersion = 0, scatterChart, heatmapChart, scatterData = [];
  let metaVersion = 0;
  const endpoint = suffix => `/api/v1/search/${encodeURIComponent(searchId)}/${suffix}`;
  const fields = Array.from(form.querySelectorAll("[data-error]"));
  function fieldError(name, message) {
    const target = fields.filter(el => name === el.dataset.error || name.startsWith(el.dataset.error + "."))
      .sort((a, b) => b.dataset.error.length - a.dataset.error.length)[0];
    if (target) target.textContent = message;
  }
  function validate() {
    fields.forEach(el => { el.textContent = ""; });
    let body;
    try { body = window.tubeSearch.formBody(form); }
    catch (error) { fieldError("video.durationSec", error.message); return null; }
    let ok = true;
    const fail = (name, message) => { ok = false; fieldError(name, message); };
    if (!body.keyword) fail("keyword", "키워드를 입력하세요");
    for (const input of form.querySelectorAll("input[name]")) {
      // Count inputs deliberately allow 1-unit typing with 100-unit spinners.
      if (!input.validity.valid && !(input.hasAttribute("data-count") && input.validity.stepMismatch && !input.validity.rangeUnderflow && !input.validity.badInput)) {
        ok = false;
        fieldError(input.name, "입력 형식과 허용 범위를 확인하세요.");
      }
    }
    for (const [section, names] of [["video", window.tubeSearch.videoRanges], ["channel", window.tubeSearch.channelRanges]]) {
      for (const key of names) {
        const b = body[section][key];
        if (b.min != null && b.max != null && b.min > b.max) fail(`${section}.${key}`, "최소는 최대보다 클 수 없습니다.");
      }
    }
    if (body.published.after && body.published.before && body.published.after > body.published.before) fail("published", "시작일은 종료일보다 늦을 수 없습니다.");
    const a = body.channel.activity;
    if (a.countMin != null && a.countMax != null && a.countMin > a.countMax) fail("channel.activity", "최소는 최대보다 클 수 없습니다.");
    if (control("createdMode").value && !Object.keys(body.channel.created).length) fail("channel.created", "선택한 개설 시기의 값을 입력하세요.");
    for (const field of form.querySelectorAll("[data-chips]")) {
      const [section, key] = field.dataset.chips.split(".").slice(1);
      if (body.video[section][key].length > Number(field.dataset.limit)) fail(field.dataset.chips, "더 추가할 수 없습니다.");
    }
    return ok ? body : null;
  }
  function setBusy(value) {
    busy = value;
    $("search-submit").disabled = value;
    $("loading").hidden = !value;
    $("results").setAttribute("aria-busy", String(value));
    for (const el of $("result-tools").querySelectorAll("select, button")) el.disabled = value;
    $("prev-page").disabled = value || !currentPage || currentPage.page <= 0;
    $("next-page").disabled = value || !currentPage || currentPage.page + 1 >= currentPage.totalPages;
  }
  async function showError(error, target = "search-error") {
    let message = error.status === 404 ? "검색 결과가 만료되었습니다. 다시 검색해 주세요." : error.message;
    if (error.data?.code === "QUOTA_BLOCKED") {
      message = "오늘 사용 가능한 한도를 모두 썼습니다. 저장된 결과만 볼 수 있습니다.";
      try { const quota = await api("/api/v1/quota"); message += ` 초기화: ${date(quota.resetAt)}`; } catch { /* Keep the actionable error. */ }
    } else if (error.status === 429) message = `이용 횟수 또는 요청 속도 한도를 초과했습니다. ${error.message}`;
    $(target).textContent = message;
    for (const item of error.data?.fieldErrors || []) fieldError(item.field, item.message);
  }
  function scheduleEstimate(immediate = false) {
    clearTimeout(estimateTimer);
    const version = ++estimateVersion;
    $("estimate").hidden = true;
    estimateTimer = setTimeout(async () => {
      let body;
      try { body = window.tubeSearch.formBody(form); } catch { return; }
      if (!body.keyword) return;
      try {
        const result = await api("/api/v1/search/estimate", {method: "POST", body: JSON.stringify(body)});
        if (version !== estimateVersion) return;
        $("estimate").textContent = result.cached ? "저장된 결과가 있어 0 units" : `예상 최대 ${number(result.estimatedUnits)} units · 남은 ${number(result.remainingUnits)} units${result.estimatedSearchesLeft == null ? "" : ` · 오늘 약 ${number(result.estimatedSearchesLeft)}회 더 검색 가능`}`;
        $("estimate").hidden = false;
      } catch { if (version === estimateVersion) $("estimate").hidden = true; }
    }, immediate ? 0 : 500);
  }
  async function loadMeta() {
    const version = ++metaVersion;
    try {
      const meta = await api(`/api/v1/meta?regionCode=${encodeURIComponent(control("video.regionCode").value)}`);
      if (version !== metaVersion) return;
      for (const select of form.querySelectorAll("select[data-meta]")) {
        const selected = Array.from(select.selectedOptions, o => o.value);
        select.replaceChildren();
        if (select.name === "video.relevanceLanguage") select.append(new Option("상관없음", ""));
        if (select.name === "channel.countries") select.append(new Option("미설정", "__unset__"));
        for (const item of meta[select.dataset.meta]) { const option = node("option", item.title || item.name); option.value = String(item.id ?? item.code); select.append(option); }
        for (const option of select.options) option.selected = selected.includes(option.value);
        if (!select.multiple && select.selectedIndex < 0) select.selectedIndex = 0;
      }
      for (const field of form.querySelectorAll("[data-chips]")) field.dataset.limit = String(field.dataset.chips.includes(".tags.") ? meta.limits.maxTags : meta.limits.maxWords);
      $("meta-error").textContent = ""; $("retry-meta").hidden = true;
    } catch { $("meta-error").textContent = "선택지를 불러오지 못했습니다. 다시 시도하세요."; $("retry-meta").hidden = false; }
  }
  $("retry-meta").addEventListener("click", loadMeta);
  function addChip(field) {
    const input = field.querySelector("[data-chip-input]");
    const text = input.value.trim().toLowerCase();
    const existing = Array.from(field.querySelectorAll("[data-token]"));
    if (!text) return true;
    if (existing.some(c => c.dataset.token === text)) { input.value = ""; return true; }
    if (existing.length >= Number(field.dataset.limit)) { fieldError(field.dataset.chips, "더 추가할 수 없습니다."); return false; }
    const chip = node("button", `${text} ×`);
    chip.type = "button"; chip.dataset.token = text;
    chip.setAttribute("aria-label", `${text} 삭제`);
    chip.addEventListener("click", () => { chip.remove(); fieldError(field.dataset.chips, ""); scheduleEstimate(); });
    field.querySelector(".chips").append(chip); input.value = "";
    fieldError(field.dataset.chips, ""); scheduleEstimate(); return true;
  }
  for (const field of form.querySelectorAll("[data-chips]")) {
    const input = field.querySelector("[data-chip-input]");
    input.addEventListener("keydown", event => { if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); addChip(field); } });
    input.addEventListener("blur", () => addChip(field));
  }
  for (const slider of form.querySelectorAll("[data-sync]")) {
    const input = control(slider.dataset.sync);
    slider.addEventListener("input", () => { input.value = input.type === "text" ? minute(Number(slider.value)) : slider.value; });
    input.addEventListener("input", () => {
      try { const value = input.type === "text" ? window.tubeSearch.duration(input.value) : Number(input.value); slider.value = String(Math.min(Number(slider.max), value)); } catch { /* Invalid text is shown by validation. */ }
    });
  }
  for (const input of form.querySelectorAll("[data-count]")) {
    input.addEventListener("keydown", event => {
      if (["ArrowUp", "ArrowDown"].includes(event.key)) {
        event.preventDefault(); input.value = String(Math.max(0, Number(input.value || 0) + (event.key === "ArrowUp" ? 100 : -100))); input.dispatchEvent(new Event("input", {bubbles: true}));
      }
    });
    input.addEventListener("input", () => { input.closest("fieldset").querySelector("[data-number-hint]").textContent = Array.from(input.closest("fieldset").querySelectorAll("[data-count]")).map(c => c.value === "" ? "조건 없음" : number(c.value)).join(" ~ "); });
  }
  for (const button of form.querySelectorAll("[data-days]")) button.addEventListener("click", () => {
    const kstDay = d => {
      const parts = new Intl.DateTimeFormat("en", {timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit"}).formatToParts(d);
      const part = key => parts.find(p => p.type === key).value;
      return `${part("year")}-${part("month")}-${part("day")}`;
    };
    const today = new Date(kstDay(new Date()) + "T00:00:00+09:00");
    control("published.before").value = kstDay(today);
    control("published.after").value = kstDay(new Date(today.getTime() - Number(button.dataset.days) * 86400000)); scheduleEstimate();
  });
  form.addEventListener("input", event => { if (!event.target.closest("#result-content")) scheduleEstimate(); });
  form.addEventListener("change", event => {
    if (event.target.name === "video.regionCode") loadMeta();
    if (!event.target.closest("#result-content")) scheduleEstimate(event.target.name === "pages");
  });
  $("reset-filters").addEventListener("click", () => {
    const keyword = control("keyword").value;
    const resultOptions = ["resultSort", "resultOrder", "resultSize"].map(n => [n, control(n).value]);
    form.reset(); control("keyword").value = keyword;
    resultOptions.forEach(([n, value]) => { control(n).value = value; });
    form.querySelectorAll(".chips").forEach(el => el.replaceChildren());
    form.querySelectorAll("[data-number-hint], [data-error]").forEach(el => { el.textContent = ""; });
    scheduleEstimate();
  });
  function showWarnings(warnings = []) {
    const messages = {PARTIAL_FAILURE: "일부 정보를 불러오지 못했습니다.", STALE_STATS: "쿼터 제한으로 저장된 통계를 표시합니다.", ACTIVITY_LIMIT: "활동 확인 한도 50채널을 초과한 채널은 제외되었습니다."};
    $("warnings").textContent = warnings.map(w => messages[w] || String(w)).join(" · ");
    $("warnings").hidden = warnings.length === 0;
  }
  function renderPage(page) {
    currentPage = page;
    $("video-list").replaceChildren();
    for (const item of page.items) {
      $("video-list").append(window.tubeSearch.videoCard(item));
    }
    $("page-status").textContent = `전체 ${number(page.totalElements)}개 · ${page.totalPages ? page.page + 1 : 0} / ${page.totalPages}쪽`;
    $("search-state").textContent = page.totalElements ? `${number(page.totalElements)}개의 영상을 찾았습니다.` : "검색 결과가 없습니다. 필터 조건을 완화해 보세요.";
    if (page.warnings) showWarnings(page.warnings);
    setBusy(busy);
  }
  function renderFunnel(funnel) {
    $("funnel").replaceChildren();
    for (const [key, title] of [["candidates","후보"],["afterVideoFilters","영상 필터"],["afterChannelFilters","채널 필터"],["afterActivityFilters","채널 활동 필터"],["final","최종"]]) {
      if (funnel[key] == null) continue;
      const row = node("div", `${title} ${number(funnel[key])}`), meter = node("meter");
      meter.min = 0; meter.max = Math.max(1, funnel.candidates); meter.value = funnel[key]; meter.setAttribute("aria-label", `${title} 남은 개수`); row.append(meter); $("funnel").append(row);
    }
    $("filter-drops").replaceChildren(node("p", `비공개·누락 값 ${number(funnel.hiddenValues ?? 0)}개`));
    for (const [key, value] of Object.entries(funnel.filterDrops || funnel.drops || {})) $("filter-drops").append(node("p", `${key}: ${number(value)}개 탈락`));
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    const body = validate();
    if (!body) { $("search-error").textContent = "필터 입력값을 확인해 주세요."; return; }
    setBusy(true); $("search-error").textContent = ""; $("search-state").textContent = "검색 중입니다.";
    ++pageVersion; ++analysisVersion;
    try {
      const result = await api("/api/v1/search", {method: "POST", body: JSON.stringify(body)});
      searchId = result.searchId;
      control("resultSort").value = "publishedAt"; control("resultOrder").value = "desc"; control("resultSize").value = "20";
      renderFunnel(result.funnel); showWarnings(result.warnings);
      $("search-quota").textContent = `${result.cached ? "저장된 결과" : "신규 검색"} · 이번 검색 ${number(result.quota.spent)} units · 오늘 남은 ${number(result.quota.remainingToday)} units`;
      $("result-content").hidden = false; renderPage(result.page);
      resetAnalysis(); scheduleEstimate(); window.tubeFilter.refreshQuota();
    } catch (error) { $("search-state").textContent = "검색을 완료하지 못했습니다. 입력 조건을 유지했습니다."; await showError(error); }
    finally { setBusy(false); }
  });
  const resultQuery = (page = 0) => new URLSearchParams({page, size: control("resultSize").value, sort: control("resultSort").value, order: control("resultOrder").value});
  async function loadPage(page = 0) {
    if (!searchId || busy) return;
    const version = ++pageVersion;
    $("search-error").textContent = ""; setBusy(true);
    try { const result = await api(endpoint(`results?${resultQuery(page)}`)); if (version === pageVersion) renderPage(result); }
    catch (error) { await showError(error); }
    finally { if (version === pageVersion) setBusy(false); }
  }
  for (const name of ["resultSort", "resultOrder", "resultSize"]) control(name).addEventListener("change", () => loadPage());
  $("prev-page").addEventListener("click", () => loadPage(currentPage.page - 1));
  $("next-page").addEventListener("click", () => loadPage(currentPage.page + 1));
  $("export-csv").addEventListener("click", async () => {
    if (!searchId) return;
    const button = $("export-csv"); button.disabled = true;
    try {
      const blob = await window.tubeFilter.download(endpoint(`export.csv?${new URLSearchParams({sort: control("resultSort").value, order: control("resultOrder").value})}`), "CSV를 내려받지 못했습니다.");
      const url = URL.createObjectURL(blob);
      const link = node("a"); link.href = url; link.download = "tube-filter.csv"; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { await showError(error); } finally { button.disabled = false; }
  });
  function resetAnalysis() {
    ++analysisVersion;
    scatterChart?.destroy(); heatmapChart?.destroy(); scatterChart = null; heatmapChart = null;
    for (const key of ["summary", "scatter", "heatmap"]) { $(`analysis-${key}`).hidden = true; $(`tab-${key}`).setAttribute("aria-selected", "false"); }
    $("analysis-state").textContent = "분석 탭을 선택하세요.";
  }
  function drawScatter() {
    scatterChart?.destroy();
    const log = $("log-scale").checked;
    const points = scatterData.filter(p => p.subscribers != null && p.views != null && (!log || (p.subscribers > 0 && p.views > 0)));
    $("scatter-note").textContent = `표시 ${number(points.length)}개 · 구독자 또는 조회수 비공개${log ? ", 0인 점" : ""}은 제외됩니다. 점을 클릭하면 영상 카드로 이동합니다.`;
    scatterChart = new Chart($("scatter-chart"), {type: "scatter", data: {datasets: [{label: "영상", data: points.map(p => ({x:p.subscribers, y:p.views, videoId:p.videoId, title:p.title})), backgroundColor:"#2356a8"}]}, options: {
      responsive:true, maintainAspectRatio:false, scales: {x:{type:log ? "logarithmic" : "linear", title:{display:true,text:"구독자 수"}}, y:{type:log ? "logarithmic" : "linear", title:{display:true,text:"조회수"}}},
      plugins:{tooltip:{callbacks:{label:context => `${context.raw.title}: 구독자 ${number(context.raw.x)}, 조회수 ${number(context.raw.y)}`}}},
      onClick: async (event, elements) => { if (elements.length) await findCard(points[elements[0].index].videoId); },
    }});
  }
  async function findCard(videoId) {
    if (!window.tubeSearch.validVideoId(videoId) || busy) return;
    let card = $(`video-${videoId}`);
    if (!card) {
      setBusy(true);
      try {
        // Locate the selected point in stored, sorted pages without a new search.
        const pages = Math.ceil(currentPage.totalElements / 50);
        for (let page = 0; page < pages; page++) {
          const query = resultQuery(page); query.set("size", "50");
          const result = await api(endpoint(`results?${query}`));
          if (result.items.some(item => item.videoId === videoId)) { control("resultSize").value = "50"; renderPage(result); card = $(`video-${videoId}`); break; }
        }
      } catch (error) { await showError(error); } finally { setBusy(false); }
    }
    card?.scrollIntoView({behavior:"smooth",block:"center"}); card?.focus({preventScroll:true});
  }
  function drawHeatmap(data) {
    heatmapChart?.destroy();
    const days = ["월","화","수","목","금","토","일"];
    const points = data.matrix.flatMap((row, day) => row.map((count, hour) => ({x:hour,y:day,count})));
    // Chart.js core has no matrix chart: paint cells with a local plugin.
    const cells = {id:"heatmapCells", beforeDatasetsDraw(chart) {
      const {ctx, scales:{x,y}} = chart;
      const width = Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0));
      const height = Math.abs(y.getPixelForValue(1) - y.getPixelForValue(0));
      ctx.save();
      for (const p of points) { ctx.fillStyle = `rgba(35,86,168,${0.06 + 0.94 * p.count / Math.max(1, data.max)})`; ctx.fillRect(x.getPixelForValue(p.x)-width/2, y.getPixelForValue(p.y)-height/2, width-1, height-1); }
      ctx.restore();
    }};
    heatmapChart = new Chart($("heatmap-chart"), {type:"scatter",plugins:[cells],data:{datasets:[{data:points,pointRadius:0,pointHitRadius:12}]},options:{responsive:true,maintainAspectRatio:false,
      scales:{x:{min:-0.5,max:23.5,ticks:{stepSize:1,callback:v=>Number.isInteger(v)&&v>=0&&v<=23 ? `${v}시` : ""}},y:{min:-0.5,max:6.5,reverse:true,ticks:{stepSize:1,callback:v=>days[v] || ""}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${days[c.raw.y]} ${c.raw.x}시: ${c.raw.count}개`}}},
    }});
    const table = node("table"); table.append(node("caption", "업로드 요일×시간대 개수 (KST)"));
    const head = node("tr"); head.append(node("th", "요일/시")); for (let hour=0; hour<24; hour++) head.append(node("th", hour)); table.append(head);
    data.matrix.forEach((row, day) => { const tr=node("tr"); tr.append(node("th",days[day])); row.forEach(count=>tr.append(node("td",count))); table.append(tr); });
    $("heatmap-table").replaceChildren(table);
  }
  async function loadAnalysis(key) {
    if (!searchId) return;
    const version = ++analysisVersion;
    for (const name of ["summary","scatter","heatmap"]) { $(`analysis-${name}`).hidden = name !== key; $(`tab-${name}`).setAttribute("aria-selected", String(name === key)); }
    $("analysis-state").textContent = "분석을 불러오는 중입니다.";
    try {
      const data = await api(endpoint(key)); if (version !== analysisVersion) return;
      if (key === "summary") {
        const content = $("analysis-summary"); content.replaceChildren(node("p", `최종 ${number(data.count)}개`));
        for (const [name,label,calc] of [["views","조회수"],["likeRatePct","좋아요율 (%)",true],["viewsPerSubPct","구독자 대비 조회수 (%)",true]]) {
          const row=node("p", `${label}: 평균 ${number(data[name].avg)} · 중앙값 ${number(data[name].median)} · 최댓값 ${number(data[name].max)}`);
          if (calc) row.append(node("span","계산값 · YouTube 제공 지표가 아님","badge")); content.append(row);
        }
      } else {
        if (typeof Chart === "undefined") throw new Error("차트 파일을 불러오지 못했습니다. 새로고침해 주세요.");
        if (key === "scatter") { scatterData=data; drawScatter(); } else drawHeatmap(data);
      }
      $("analysis-state").textContent = "";
    } catch (error) { if (version === analysisVersion) await showError(error,"analysis-state"); }
  }
  const tabs = Array.from(document.querySelectorAll("[data-analysis]"));
  tabs.forEach((tab,index) => {
    tab.addEventListener("click", () => loadAnalysis(tab.dataset.analysis));
    tab.addEventListener("keydown", event => {
      if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length-1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus(); loadAnalysis(tabs[next].dataset.analysis);
    });
  });
  $("log-scale").addEventListener("change", () => { if (scatterChart) drawScatter(); });
  const mobile = window.matchMedia("(max-width: 760px)");
  $("filter-panel").open = !mobile.matches;
  mobile.addEventListener("change", event => { $("filter-panel").open = !event.matches; });
  const metaReady = loadMeta();
  async function applyLoaded(conditions) {
    await metaReady;
    // Load the saved region before restoring selections from that region.
    control("video.regionCode").value = conditions.video?.regionCode || "KR";
    await loadMeta();
    window.tubeSearch.applyConditions(form, conditions, addChip);
    fields.forEach(el => { el.textContent = ""; });
    $("preset-message").textContent = "필터를 불러왔습니다. 검색을 눌러 실행하세요";
    scheduleEstimate();
  }
  function memberOnly() {
    if (document.body.dataset.member === "true") return true;
    $("preset-message").replaceChildren(node("span", "로그인 후 이용할 수 있습니다. "));
    const link = node("a", "로그인"); link.href = "/login"; $("preset-message").append(link); return false;
  }
  const presetError = error => { if (error.status === 401) window.location.assign("/login"); else $("preset-message").textContent = error.message; };
  $("save-preset").addEventListener("click", () => { if (memberOnly()) { $("preset-save").hidden = false; $("preset-name").focus(); } });
  $("cancel-preset").addEventListener("click", () => { $("preset-save").hidden = true; });
  $("submit-preset").addEventListener("click", async () => {
    if (!memberOnly()) return;
    const name = $("preset-name").value.trim();
    if (!name || name.length > 30) { $("preset-message").textContent = "이름은 1~30자로 입력하세요."; return; }
    $("submit-preset").disabled = true;
    try {
      const conditions = window.tubeSearch.formBody(form); delete conditions.keyword;
      await api("/api/v1/presets", {method:"POST", body:JSON.stringify({name, conditions})});
      $("preset-message").textContent = "프리셋을 저장했습니다."; $("preset-save").hidden = true;
    } catch (error) { presetError(error); } finally { $("submit-preset").disabled = false; }
  });
  $("load-presets").addEventListener("click", async () => {
    if (!memberOnly()) return;
    $("load-presets").disabled = true;
    try {
      const presets = await api("/api/v1/presets"); $("preset-options").replaceChildren(); $("preset-options").hidden = false;
      if (!presets.length) $("preset-message").textContent = "저장된 프리셋이 없습니다.";
      for (const preset of presets) {
        const button = node("button", preset.name); button.type = "button";
        button.addEventListener("click", async () => {
          button.disabled = true;
          try { await applyLoaded((await api(`/api/v1/presets/${encodeURIComponent(preset.id)}`)).conditions); $("preset-options").hidden = true; }
          catch (error) { presetError(error); } finally { button.disabled = false; }
        }); $("preset-options").append(button);
      }
    } catch (error) { presetError(error); } finally { $("load-presets").disabled = false; }
  });
  async function restoreFromLink() {
    const query = new URLSearchParams(window.location.search);
    if (!query.has("preset") && !query.has("history")) return;
    if (!memberOnly()) return;
    try {
      let conditions;
      if (query.has("preset")) conditions = (await api(`/api/v1/presets/${encodeURIComponent(query.get("preset"))}`)).conditions;
      else {
        const row = (await api("/api/v1/history")).find(row => String(row.id) === query.get("history"));
        if (!row) throw new Error("검색 기록을 찾을 수 없습니다.");
        conditions = {...row.conditions, keyword:row.keyword};
      }
      await applyLoaded(conditions);
    } catch (error) { presetError(error); }
  }
  restoreFromLink();
})();
