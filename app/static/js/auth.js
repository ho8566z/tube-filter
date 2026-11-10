"use strict";

(() => {
  const form = document.getElementById("auth-form");
  const signup = form.dataset.mode === "signup";
  const loginId = form.elements.loginId;
  const password = form.elements.password;
  const submit = document.getElementById("submit-auth");
  const formError = document.getElementById("form-error");
  const api = window.tubeFilter.api;
  let busy = false;
  let checkVersion = 0;
  const fieldError = (field, message) => {
    const element = document.getElementById(`${field}-error`);
    if (element) element.textContent = message;
    if (form.elements[field]) form.elements[field].setAttribute("aria-invalid", String(Boolean(message)));
  };
  const updateSubmit = () => { submit.disabled = busy || (signup && !form.elements.agreePrivacy.checked); };
  const validatePasswords = () => {
    const value = password.value;
    const valid = value.length >= 8 && value.length <= 64 && /[a-zA-Z]/.test(value)
      && /[0-9]/.test(value) && new TextEncoder().encode(value).length <= 72;
    fieldError("password", value && !valid ? "영문과 숫자를 포함한 8~64자(UTF-8 72바이트 이하)를 입력해 주세요." : "");
    const match = value === form.elements.passwordConfirm.value;
    fieldError("passwordConfirm", form.elements.passwordConfirm.value && !match ? "비밀번호가 일치하지 않습니다." : "");
    return valid && match;
  };

  if (signup) {
    form.elements.agreePrivacy.addEventListener("change", updateSubmit);
    password.addEventListener("input", validatePasswords);
    form.elements.passwordConfirm.addEventListener("input", validatePasswords);
    loginId.addEventListener("input", () => {
      checkVersion += 1;
      fieldError("loginId", "");
    });
    loginId.addEventListener("blur", async () => {
      const version = ++checkVersion;
      const value = loginId.value;
      if (!/^[a-z][a-z0-9]{3,19}$/.test(value)) {
        fieldError("loginId", "영문 소문자로 시작하는 소문자·숫자 4~20자를 입력해 주세요.");
        return;
      }
      try {
        const result = await api(`/api/v1/auth/check-id?loginId=${encodeURIComponent(value)}`);
        if (version !== checkVersion) return;
        fieldError("loginId", result.available ? "" : "이미 사용 중입니다.");
        if (result.available) document.getElementById("loginId-error").textContent = "사용 가능합니다.";
      } catch (error) {
        if (version === checkVersion) fieldError("loginId", error.message);
      }
    });
  } else if (new URLSearchParams(window.location.search).get("signup") === "success") {
    document.getElementById("signup-notice").hidden = false;
    window.history.replaceState(null, "", "/login");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    formError.textContent = "";
    if (signup && !validatePasswords()) return;
    busy = true;
    // Ignore any in-flight availability result once the authoritative signup starts.
    checkVersion += 1;
    updateSubmit();
    const body = { loginId: loginId.value, password: password.value };
    if (signup) {
      body.passwordConfirm = form.elements.passwordConfirm.value;
      body.agreePrivacy = form.elements.agreePrivacy.checked;
      for (const field of ["loginId", "password", "passwordConfirm", "agreePrivacy"]) fieldError(field, "");
    }
    try {
      await api(`/api/v1/auth/${signup ? "signup" : "login"}`, {
        method: "POST", body: JSON.stringify(body),
      });
      // Login rotates the session and CSRF token. The destination renders a fresh meta token.
      window.location.assign(signup ? "/login?signup=success" : "/");
    } catch (error) {
      formError.textContent = error.message;
      if (signup) {
        for (const item of error.data?.fieldErrors || []) fieldError(item.field, item.message);
        if (error.status === 409) fieldError("loginId", error.message);
      }
      busy = false;
      updateSubmit();
    }
  });
})();
