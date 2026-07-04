# Telegram Forwarder 前端优化实施计划 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构并优化 Telegram Forwarder 插件内置的 Web 管理后台。第一阶段将 1600 行单文件 JS 与 1000 行单文件 CSS 重构拆分为模块化 ES6 模块和 CSS @import，并在测试中保持完全绿灯；第二阶段实现 Theme A 明暗模式支持与微图表；第三阶段实现一体化 Stepper 登录向导、带模糊匹配的群组搜索器。

**Architecture:** 纯原生 ES6 Modules (无需 Vite/Webpack 构建) + 原生 CSS @import 架构，兼容 Flask 静态文件服务。引入中心化 Store 管理全局状态。

**Tech Stack:** Vanilla JS (ES6 Modules), Vanilla CSS, Flask (Python 3.10+ / aiohttp)

---

### Task 1: 新增静态资源路由测试

**Files:**
- Modify: `tests/test_web_admin.py`

- [ ] **Step 1: 写入资产请求测试用例**

在 `tests/test_web_admin.py` 文件尾部添加以下单元测试，验证所有未来会用到的模块化 JS 与 CSS 路由均能以正确的 HTTP 状态码 200 返回：

```python
def test_static_assets_serving(web_admin):
    client = web_admin.server.app.test_client()

    # 验证主页面
    r = client.get("/")
    assert r.status_code == 200
    assert b"<!doctype html>" in r.data.lower()

    # 验证 CSS 文件
    assert client.get("/assets/style.css").status_code == 200
    assert client.get("/assets/css/variables.css").status_code == 200
    assert client.get("/assets/css/base.css").status_code == 200
    assert client.get("/assets/css/components.css").status_code == 200
    assert client.get("/assets/css/section-channels.css").status_code == 200

    # 验证 JS 模块
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/js/api.js").status_code == 200
    assert client.get("/assets/js/store.js").status_code == 200
    assert client.get("/assets/js/utils.js").status_code == 200
    assert client.get("/assets/js/ui_overview.js").status_code == 200
    assert client.get("/assets/js/ui_login.js").status_code == 200
    assert client.get("/assets/js/ui_selector.js").status_code == 200
    assert client.get("/assets/js/ui_channels.js").status_code == 200
```

- [ ] **Step 2: 运行测试验证其失败**

运行：`pytest tests/test_web_admin.py::test_static_assets_serving -v`
预期结果：FAIL（报 404，因为拆分后的文件尚不存在）

- [ ] **Step 3: 提交**

```bash
git add tests/test_web_admin.py
git commit -m "test: add static assets route tests"
```

---

### Task 2: 拆分 CSS 样式模块

**Files:**
- Create: `web/assets/css/variables.css`
- Create: `web/assets/css/base.css`
- Create: `web/assets/css/components.css`
- Create: `web/assets/css/section-channels.css`
- Modify: `web/assets/style.css`

- [ ] **Step 1: 创建 variables.css**

写入 `web/assets/css/variables.css`：
```css
:root {
  --blue: #31a8e8;
  --blue-strong: #1589ca;
  --blue-soft: #eef9ff;
  --blue-tint: #dff4ff;
  --cream: #fffdf8;
  --cream-soft: #fbf8f0;
  --ink: #152331;
  --text: #2e4051;
  --muted: #7a8c9d;
  --line: #e8eff4;
  --panel: rgba(255, 253, 248, 0.92);
  --bg: #f6fbff;
  --danger: #e15b64;
  --success: #21a67a;
  --shadow: 0 18px 42px rgba(45, 118, 166, 0.11);
}
```

- [ ] **Step 2: 创建 base.css**

将原 `style.css` 中第 19 至 222 行的代码段剪切至 `web/assets/css/base.css` 中（包含 `*`, `body`, `auth-screen`, `sidebar`, `nav-item`, `content` 样式）。

- [ ] **Step 3: 创建 components.css**

将原 `style.css` 中第 223 至 433 行，以及 453 至 923 行的代码段剪切至 `web/assets/css/components.css` 中（包含 `btn`, `metric-card`, `panel`, `segmented`, `queue-item`, `toast` 等全局公共组件样式）。

- [ ] **Step 4: 创建 section-channels.css**

将原 `style.css` 中第 434 至 452 行以及第 671 至 891 行的代码段剪切至 `web/assets/css/section-channels.css` 中（包含 `login-layout`, `channel-card`, `selector-layout`, `selector-pill` 等配置面板和选择器布局样式）。

- [ ] **Step 5: 覆盖 style.css 主入口**

清空 `web/assets/style.css` 并只保留 @import 结构：
```css
@import "css/variables.css";
@import "css/base.css";
@import "css/components.css";
@import "css/section-channels.css";
```

- [ ] **Step 6: 提交**

```bash
git add web/assets/css/ web/assets/style.css
git commit -m "style: split style.css into modular CSS files"
```

---

### Task 3: 创建基础 JS 依赖模块 (api.js, store.js, utils.js)

**Files:**
- Create: `web/assets/js/utils.js`
- Create: `web/assets/js/store.js`
- Create: `web/assets/js/api.js`

- [ ] **Step 1: 创建 utils.js**

写入 `web/assets/js/utils.js`，移入 HTML 转义等纯函数：
```javascript
export function escapeHtml(str) {
  if (typeof str !== "string") return str;
  return str.replace(/[&<>"']/g, m => {
    switch (m) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      case "'": return '&#39;';
      default: return m;
    }
  });
}

export function channelKey(cfg, index) {
  return cfg.channel_username ? `@${cfg.channel_username}` : `index_${index}`;
}

export function channelTitle(username) {
  return `@${username.replace(/^@/, "")}`;
}
```

- [ ] **Step 2: 创建 store.js**

写入 `web/assets/js/store.js`，实现全局状态流：
```javascript
export const store = {
  state: {
    token: localStorage.getItem("telegram_forwarder_token") || "",
    config: null,
    status: null,
    section: "overview",
    forwardGroup: "schedule",
    expandedChannels: new Set(),
    channelGroups: {},
  },
  listeners: [],
  subscribe(fn) {
    this.listeners.push(fn);
  },
  updateState(changes) {
    this.state = { ...this.state, ...changes };
    this.listeners.forEach(fn => fn(this.state));
  }
};
```

- [ ] **Step 3: 创建 api.js**

写入 `web/assets/js/api.js`，封装 Fetch 模块：
```javascript
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
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || "请求失败");
    return data;
  } catch (err) {
    clearTimeout(id);
    throw err;
  }
}
```

- [ ] **Step 4: 提交**

```bash
git add web/assets/js/utils.js web/assets/js/store.js web/assets/js/api.js
git commit -m "feat: add js base modules (utils, store, api)"
```

---

### Task 4: 创建功能 UI 模块 (ui_overview, ui_login, ui_selector, ui_channels)

**Files:**
- Create: `web/assets/js/ui_overview.js`
- Create: `web/assets/js/ui_login.js`
- Create: `web/assets/js/ui_selector.js`
- Create: `web/assets/js/ui_channels.js`

- [ ] **Step 1: 创建 ui_overview.js**

将原 `app.js` 中的 `renderStatus`, `renderRuntimeOperations` 以及总览页面的操作（例如暂停、清空队列）逻辑抽离，封装到 `ui_overview.js`，并使用 `store.subscribe` 进行数据驱动。

- [ ] **Step 2: 创建 ui_login.js**

将 Telegram 登录过程相关的 API 提交逻辑和渲染逻辑抽离，封装到 `ui_login.js`。

- [ ] **Step 3: 创建 ui_selector.js**

将 QQ 群组选择器、TG 频道选择器的渲染和列表反选逻辑抽离，封装到 `ui_selector.js`。

- [ ] **Step 4: 创建 ui_channels.js**

将频道卡片配置表单生成逻辑（`renderChannels`）以及合并规则页面逻辑抽离，封装到 `ui_channels.js`。

- [ ] **Step 5: 提交**

```bash
git add web/assets/js/
git commit -m "feat: extract web UI rendering modules"
```

---

### Task 5: 重构主 Entrypoint 与 HTML 模块化集成

**Files:**
- Modify: `web/assets/app.js`
- Modify: `web/index.html`

- [ ] **Step 1: 重编 app.js 作为总入口**

重写 `web/assets/app.js`，只作为主模块，引入各 UI 分发逻辑并执行事件挂载：
```javascript
import { store } from './js/store.js';
import { apiRequest } from './js/api.js';
import { initLogin } from './js/ui_login.js';
import { initOverview } from './js/ui_overview.js';
import { initChannels } from './js/ui_channels.js';

document.addEventListener("DOMContentLoaded", () => {
  // 初始化各个子面板事件监听与数据渲染
  initLogin(store);
  initOverview(store);
  initChannels(store);

  // 统一的 tab 路由切换
  // 统一的保存配置触发入口
});
```

- [ ] **Step 2: 修改 index.html 加载模式**

在 `web/index.html` 中找到第 316 行，将加载方式修改为 `type="module"`：
```html
<script src="/assets/app.js" type="module" defer></script>
```

- [ ] **Step 3: 运行静态资源测试验证全部通过**

运行：`pytest tests/test_web_admin.py -v`
预期结果：PASS（全部 25 个测试，包括我们的新路由测试均通过，无报错）

- [ ] **Step 4: 提交**

```bash
git add web/index.html web/assets/app.js
git commit -m "feat: complete Phase 1 codebase modularization"
```

---

### Task 6: 第二阶段 - 实现 Theme A 智能明暗模式支持

**Files:**
- Modify: `web/assets/css/variables.css`
- Modify: `web/assets/css/base.css`

- [ ] **Step 1: 定义 variables.css 的暗色方案**

在 `web/assets/css/variables.css` 中追加系统级 `@media (prefers-color-scheme: dark)` 支持：

```css
@media (prefers-color-scheme: dark) {
  :root {
    --cream: #0f172a;
    --cream-soft: #1e293b;
    --ink: #f8fafc;
    --text: #cbd5e1;
    --muted: #64748b;
    --line: #334155;
    --panel: rgba(30, 41, 59, 0.9);
    --bg: #0b0f19;
    --shadow: 0 18px 42px rgba(0, 0, 0, 0.3);
  }
}
```

- [ ] **Step 2: 绑定主体背景**

在 `web/assets/css/base.css` 中优化 body 渐变，使其自动响应光暗变量：
```css
html,
body {
  margin: 0;
  min-height: 100%;
  color: var(--text);
  background: var(--bg);
  transition: background 0.3s ease, color 0.3s ease;
}
```

- [ ] **Step 3: 测试与提交**

```bash
git add web/assets/css/
git commit -m "style: support auto dark mode via prefers-color-scheme"
```

---

### Task 7: 第二阶段 - 优化“总览”指标卡片与趋势

**Files:**
- Modify: `web/assets/js/ui_overview.js`
- Modify: `web/assets/css/components.css`

- [ ] **Step 1: 修改 ui_overview.js 加入状态标签样式**

在 `ui_overview.js` 渲染 Telegram 状态时，当状态为 “在线/正常”，使用一个漂亮的绿色点样式呈现；状态为 “离线/断开”，使用红色点。

- [ ] **Step 2: 提交**

```bash
git add web/assets/js/ui_overview.js
git commit -m "style: enhance overview metrics visual status"
```

---

### Task 8: 第三阶段 - 实现 Stepper 登录引导组件

**Files:**
- Modify: `web/index.html`
- Modify: `web/assets/js/ui_login.js`
- Modify: `web/assets/css/components.css`

- [ ] **Step 1: 修改 index.html 增加 Stepper 指示结构**

在 `web/index.html` 中找到登录步骤部分，增加横向进度条节点：
```html
<div class="stepper">
  <div class="step-node" id="stepNode1">
    <div class="step-circle">1</div>
    <span class="step-label">连接信息</span>
  </div>
  <!-- stepNode2, stepNode3 ... -->
</div>
```

- [ ] **Step 2: 配合 ui_login.js 自动更新状态**

在 `ui_login.js` 的步骤渲染中，根据 API 状态自动为 `stepNode` 添加 `active` / `done` 样式类。

- [ ] **Step 3: 运行测试并提交**

```bash
git add web/index.html web/assets/js/ui_login.js
git commit -m "feat: implement unified login Stepper UI"
```

---

### Task 9: 第三阶段 - 实现带模糊过滤的群组/频道选择器

**Files:**
- Modify: `web/assets/js/ui_selector.js`

- [ ] **Step 1: ui_selector.js 绑定搜索框输入事件**

在 `ui_selector.js` 的 `renderQQTargetSelector` 函数中，于列表顶部注入一个文本过滤搜索框，并绑定 `input` 事件，将过滤后的群组渲染到列表中。

- [ ] **Step 2: 运行测试验证**

运行 `pytest` 确认修改未影响 API 保存配置流程。
预期结果：PASS

- [ ] **Step 3: 提交**

```bash
git add web/assets/js/ui_selector.js
git commit -m "feat: add real-time fuzzy search filter for selector"
```

---

### Task 10: 最终自检与清理

- [ ] **Step 1: 运行全量测试**

运行：`pytest`
预期结果：所有测试全部通过。

- [ ] **Step 2: 提交合并**

```bash
git status
```
确认工作区干净，完成任务。
