"use strict";

window.tubeFilter = {
  async api(path, options = {}) {
    const headers = new Headers(options.headers);
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) {
      headers.set("X-CSRF-Token", document.querySelector('meta[name="csrf-token"]').content);
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      const error = new Error(data.message || "요청을 처리하지 못했습니다.");
      error.data = data;
      error.status = response.status;
      throw error;
    }
    return data;
  },
};

window.tubeFilter.refreshQuota = async () => {
  const status = document.getElementById("quota-status");
  const bar = document.getElementById("quota-bar");
  try {
    const quota = await window.tubeFilter.api("/api/v1/quota");
    const reset = new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).format(new Date(quota.resetAt));
    status.textContent = `오늘 사용 ${quota.usedUnits.toLocaleString("ko-KR")} / ${quota.softLimitUnits.toLocaleString("ko-KR")} units · 초기화 ${reset}(KST)`;
    const blocked = quota.usedUnits >= quota.softLimitUnits;
    bar.max = quota.softLimitUnits;
    bar.value = Math.min(quota.usedUnits, quota.softLimitUnits);
    bar.dataset.level = blocked ? "blocked" : quota.usedUnits / quota.softLimitUnits > 0.8 ? "warning" : "normal";
    bar.hidden = false;
    if (blocked) status.textContent += " · 오늘 사용 가능한 한도를 모두 썼습니다.";
  } catch {
    status.textContent = "쿼터 정보를 불러오지 못했습니다";
  }
};
window.tubeFilter.refreshQuota();

document.getElementById("logout")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await window.tubeFilter.api("/api/v1/auth/logout", { method: "POST" });
    window.location.assign("/login");
  } catch (error) {
    document.getElementById("global-message").textContent = error.message;
    button.disabled = false;
  }
});
