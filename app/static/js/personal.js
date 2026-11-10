"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const root = $("personal-page");
  if (!root) return;
  const {node, date, number, videoCard} = window.tubeSearch;
  const api = (path, options) => window.tubeFilter.api(path, options);
  const message = text => { $("page-message").textContent = text; };
  function errorMessage(error) {
    if (error.status === 401) { window.location.assign("/login"); return; }
    message(error.message); $("retry-page").hidden = false;
  }
  function button(text, action) {
    const el = node("button", text); el.type = "button";
    el.addEventListener("click", async () => {
      el.disabled = true;
      try { await action(); } catch (error) { errorMessage(error); } finally { el.disabled = false; }
    }); return el;
  }
  function loadLink(text, kind, id) {
    const link = node("a", text); link.href = `/?${kind}=${encodeURIComponent(id)}`; return link;
  }
  let pendingDelete;
  function confirmDelete(text, action) {
    pendingDelete = action; $("confirm-message").textContent = text; $("confirm-action").showModal();
  }
  $("confirm-no").addEventListener("click", () => $("confirm-action").close());
  $("confirm-action").addEventListener("close", () => { pendingDelete = null; });
  $("confirm-yes").addEventListener("click", async () => {
    if (!pendingDelete) return;
    $("confirm-yes").disabled = true;
    try { await pendingDelete(); $("confirm-action").close(); }
    catch (error) { $("confirm-action").close(); errorMessage(error); }
    finally { $("confirm-yes").disabled = false; }
  });
  const page = root.dataset.page;
  let favoritesPage = 0, charts = [], loading = false;
  function warnings(values = []) {
    const labels = {STALE_STATS:"쿼터 제한으로 저장된 통계를 표시합니다.", PARTIAL_FAILURE:"일부 정보를 불러오지 못했습니다."};
    $("page-warnings").textContent = values.map(v => labels[v] || String(v)).join(" · ");
    $("page-warnings").hidden = !values.length;
  }
  function table(id, caption, headings, rows) {
    const table = node("table"), head = node("tr"); table.append(node("caption", caption));
    headings.forEach(value => head.append(node("th", value))); table.append(head);
    rows.forEach(values => { const row = node("tr"); values.forEach(value => row.append(node("td", value))); table.append(row); });
    $(id).replaceChildren(table);
  }
  function drawPattern(pattern) {
    charts.forEach(chart => chart.destroy()); charts = [];
    const days = ["월","화","수","목","금","토","일"];
    table("monthly-table", "월별 업로드", ["월", "영상 수"], pattern.monthly.map(row => [row.month, row.count]));
    table("channel-heatmap-table", "업로드 요일×시간대 (KST)", ["요일/시", ...Array.from({length:24}, (_,h) => `${h}시`)], pattern.matrix.map((row,d) => [days[d], ...row]));
    if (typeof Chart === "undefined") throw new Error("차트를 불러오지 못했습니다. 아래 표에서 같은 데이터를 확인하세요.");
    charts.push(new Chart($("monthly-chart"), {type:"bar", data:{labels:pattern.monthly.map(row=>row.month), datasets:[{label:"업로드 영상 수",data:pattern.monthly.map(row=>row.count),backgroundColor:"#2356a8"}]},options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true,ticks:{precision:0}}}}}));
    const points = pattern.matrix.flatMap((row,d) => row.map((count,h) => ({x:h,y:d,count})));
    const max = Math.max(1,...points.map(p=>p.count));
    const cells = {id:"channelCells",beforeDatasetsDraw(chart) {
      const {ctx,scales:{x,y}} = chart;
      const width = Math.abs(x.getPixelForValue(1)-x.getPixelForValue(0)), height = Math.abs(y.getPixelForValue(1)-y.getPixelForValue(0));
      ctx.save();
      for (const p of points) { ctx.fillStyle = `rgba(35,86,168,${0.06+0.94*p.count/max})`; ctx.fillRect(x.getPixelForValue(p.x)-width/2,y.getPixelForValue(p.y)-height/2,width-1,height-1); }
      ctx.restore();
    }};
    charts.push(new Chart($("channel-heatmap"), {type:"scatter",plugins:[cells],data:{datasets:[{data:points,pointRadius:0,pointHitRadius:12}]},options:{responsive:true,maintainAspectRatio:false,
      scales:{x:{min:-0.5,max:23.5,ticks:{stepSize:1,callback:v=>Number.isInteger(v)&&v>=0&&v<=23 ? `${v}시` : ""}},y:{min:-0.5,max:6.5,reverse:true,ticks:{stepSize:1,callback:v=>days[v] || ""}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${days[c.raw.y]} ${c.raw.x}시: ${c.raw.count}개`}}},
    }}));
  }
  async function presets() {
    const rows = await api("/api/v1/presets"); $("personal-list").replaceChildren();
    for (const item of rows) {
      const row = node("tr"), name = node("td",item.name), actions = node("td");
      actions.append(loadLink("적용","preset",item.id), button("이름 변경", () => {
        const editor = node("div"), label = node("label","새 프리셋 이름"), input = node("input");
        input.value = item.name; input.maxLength = 30; label.append(input);
        editor.append(label, button("저장", async () => {
          const nextName = input.value.trim();
          if (!nextName || nextName.length > 30) { message("이름은 1~30자로 입력하세요."); return; }
          const detail = await api(`/api/v1/presets/${item.id}`);
          await api(`/api/v1/presets/${item.id}`, {method:"PUT",body:JSON.stringify({name:nextName,conditions:detail.conditions})});
          await load(); message("이름을 변경했습니다.");
        }), button("취소", () => editor.remove())); name.replaceChildren(editor); input.focus();
      }), button("삭제", () => confirmDelete(`‘${item.name}’ 프리셋을 삭제할까요?`, async () => { await api(`/api/v1/presets/${item.id}`, {method:"DELETE"}); await load(); })));
      row.append(name,node("td",date(item.createdAt)),actions); $("personal-list").append(row);
    }
    message(rows.length ? "" : "저장된 프리셋이 없습니다.");
  }
  async function history() {
    const rows = await api("/api/v1/history"); $("personal-list").replaceChildren(); $("clear-history").disabled = !rows.length;
    for (const item of rows) {
      const row = node("tr"), actions = node("td");
      actions.append(loadLink("불러오기","history",item.id),button("삭제", () => confirmDelete("이 검색 기록을 삭제할까요?", async () => { await api(`/api/v1/history/${item.id}`, {method:"DELETE"}); await load(); })));
      row.append(node("td",item.keyword),node("td",conditionSummary(item.conditions)),node("td",number(item.resultCount)),node("td",date(item.searchedAt)),actions); $("personal-list").append(row);
    }
    message(rows.length ? "" : "검색 기록이 없습니다.");
  }
  function conditionSummary(c) {
    const labels = {relevance:"관련도",date:"최신",viewCount:"조회수",rating:"평점"};
    const parts = [`후보 ${c.pages || 2}쪽`,labels[c.order] || "관련도"];
    if (c.published?.after) parts.push(`시작 ${date(c.published.after)}`);
    if (c.published?.before) parts.push(`종료 ${date(c.published.before)}`);
    for (const [section,key,label] of [["video","durationSec","길이(초)"],["video","views","조회수"],["video","likes","좋아요"],["video","comments","댓글"],["video","likeRatePct","좋아요율(%)"],["video","commentRatePct","댓글 참여율(%)"],["channel","subscribers","구독자"],["channel","viewsPerSubPct","구독자 대비 조회수(%)"],["channel","videoCount","채널 영상 수"],["channel","avgViews","채널 평균 조회수"]]) {
      const range = c[section]?.[key];
      if (range && (range.min != null || range.max != null)) parts.push(`${label} ${range.min ?? "제한 없음"}~${range.max ?? "제한 없음"}`);
    }
    const v = c.video || {};
    if (v.shorts && v.shorts !== "ANY") parts.push(v.shorts === "ONLY" ? "쇼츠만" : "쇼츠 제외");
    if (v.tags?.include?.length) parts.push(`포함 태그 ${v.tags.include.join(", ")}`);
    if (v.words?.must?.length) parts.push(`포함 단어 ${v.words.must.join(", ")}`);
    if (v.weekdays?.length) parts.push(`요일 ${v.weekdays.map(d=>["월","화","수","목","금","토","일"][d]).join(", ")}`);
    if (v.hours && (v.hours.from != null || v.hours.to != null)) parts.push(`시간 ${v.hours.from ?? 0}~${v.hours.to ?? 23}시`);
    return parts.join(" · ");
  }
  async function favorites() {
    let result = await api(`/api/v1/favorites?page=${favoritesPage}&size=20`);
    if (!result.items.length && favoritesPage > 0) { favoritesPage--; result = await api(`/api/v1/favorites?page=${favoritesPage}&size=20`); }
    $("personal-list").replaceChildren(...result.items.map(item => videoCard(item,true,load)));
    warnings(result.warnings); $("favorites-prev").disabled = favoritesPage === 0; $("favorites-next").disabled = favoritesPage+1 >= result.totalPages;
    $("favorites-status").textContent = `전체 ${number(result.totalElements)}개 · ${result.totalPages ? favoritesPage+1 : 0} / ${result.totalPages}쪽`;
    message(result.totalElements ? "" : "즐겨찾기가 없습니다."); window.tubeFilter.refreshQuota();
  }
  async function channel() {
    let result;
    try { result = await api(`/api/v1/channels/${encodeURIComponent(root.dataset.channelId)}`); }
    catch (error) {
      if (error.status === 404) {
        $("channel-summary").replaceChildren(node("h2","404 · 채널을 찾을 수 없습니다.")); $("channel-pattern").hidden = true;
        $("personal-list").replaceChildren(); document.title = "채널을 찾을 수 없습니다 · tube-filter";
      } throw error;
    }
    const c = result.channel, link = node("a","YouTube에서 보기");
    link.href = `https://www.youtube.com/channel/${encodeURIComponent(c.id)}`; link.target = "_blank"; link.rel = "noopener noreferrer";
    $("channel-summary").replaceChildren(node("h2",c.title),node("p",`구독자 ${number(c.subscribers)} · 영상 수 ${number(c.videoCount)} · 개설일 ${date(c.createdAt)} · 국가 ${c.country || "미설정"}`),link);
    $("personal-list").replaceChildren(...result.recentVideos.map(item=>videoCard(item)));
    warnings(result.warnings); message(result.recentVideos.length ? "" : "최근 업로드 영상이 없습니다.");
    $("channel-pattern").hidden = false; drawPattern(result.pattern); window.tubeFilter.refreshQuota();
  }
  function bindAccountForm(id, path, method, success) {
    const form = $(id);
    form.addEventListener("submit", async event => {
      event.preventDefault(); if (!form.reportValidity()) return;
      const submit = form.querySelector('button[type="submit"]'); submit.disabled = true;
      for (const el of form.querySelectorAll(".error")) el.textContent = "";
      try {
        const body = Object.fromEntries(Array.from(form.elements).filter(el => el.name).map(el => [el.name, el.value]));
        await api(path,{method,body:JSON.stringify(body)}); form.reset(); success();
      } catch (error) {
        if (error.data?.code === "WRONG_PASSWORD") $(id === "password-form" ? "currentPassword-error" : "password-error").textContent = error.message;
        else if (error.data?.fieldErrors?.length) for (const field of error.data.fieldErrors) { const el = $(`${field.field}-error`); if (el) el.textContent = field.message; }
        else errorMessage(error);
      } finally { submit.disabled = false; }
    });
  }
  if (page === "me") {
    bindAccountForm("password-form","/api/v1/me/password","PATCH", () => message("변경되었습니다"));
    bindAccountForm("withdraw-form","/api/v1/me","DELETE", () => window.location.assign("/login"));
    $("open-withdraw").addEventListener("click", () => { $("withdraw-form").reset(); $("password-error").textContent = ""; $("withdraw-modal").showModal(); });
    $("cancel-withdraw").addEventListener("click", () => $("withdraw-modal").close());
    $("withdraw-modal").addEventListener("close", () => $("withdraw-form").reset());
  }
  $("clear-history")?.addEventListener("click", () => confirmDelete("검색 기록 전체를 삭제할까요?", async () => { await api("/api/v1/history/all", {method:"DELETE"}); await load(); }));
  $("favorites-prev")?.addEventListener("click", () => { if (!loading && favoritesPage > 0) { favoritesPage--; load(); } });
  $("favorites-next")?.addEventListener("click", () => { if (!loading) { favoritesPage++; load(); } });
  async function load() {
    if (loading) return;
    loading = true; message("불러오는 중입니다."); $("retry-page").hidden = true;
    try {
      if (page === "presets") await presets();
      else if (page === "history") await history();
      else if (page === "favorites") await favorites();
      else if (page === "channel") await channel();
      else { const user = await api("/api/v1/me"); $("account-info").textContent = `${user.loginId} · 가입일 ${date(user.createdAt)}`; message(""); }
    } catch (error) { errorMessage(error); } finally { loading = false; }
  }
  $("retry-page").addEventListener("click", load); load();
})();
