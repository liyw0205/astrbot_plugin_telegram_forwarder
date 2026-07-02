import { store } from './store.js';

export async function apiRequest(path, method = 'GET', body = null, timeout = 30000) {
  const headers = {
    'Content-Type': 'application/json',
    'X-Admin-Token': store.state.token
  };
  const options = { method, headers };
  if (body) options.body = JSON.stringify(body);

  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  options.signal = controller.signal;

  try {
    const res = await fetch(path, options);
    clearTimeout(id);
    if (res.status === 401 || res.status === 410) {
      store.updateState({ token: "" });
      localStorage.removeItem("telegram_forwarder_token");
      throw new Error("登录已过期，请重新输入 Token");
    }
    const payload = await res.json();
    if (!res.ok || payload?.ok === false) {
      throw new Error(payload?.message || "请求失败");
    }
    const data = payload?.data ?? {};
    if (data && typeof data === "object" && !Array.isArray(data) && payload?.message && !data.message) {
      data.message = payload.message;
    }
    return data;
  } catch (err) {
    clearTimeout(id);
    throw err;
  }
}
