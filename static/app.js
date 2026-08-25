"use strict";

// ---------------------------------------------------------------- 状态
const state = {
  items: [], // {id, filename, source, track, title, artist, album, statusText, statusCls, dirty}
  aiRunning: false,
};

const $ = (sel) => document.querySelector(sel);
const tbody = $("#tbody");

// ---------------------------------------------------------------- 工具
function toast(msg, ms = 3000) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}
function setStatusbar(text) {
  $("#statusbar").textContent = text;
}
async function api(url, opts = {}) {
  const resp = await fetch(url, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `请求失败 (${resp.status})`);
  return data;
}

// ---------------------------------------------------------------- 表格渲染
function rowTemplate(item) {
  const tr = document.createElement("tr");
  tr.dataset.id = item.id;

  const tdFile = document.createElement("td");
  tdFile.className = "col-file";
  const fn = document.createElement("div");
  fn.className = "fname";
  const tag = document.createElement("span");
  tag.className = "src-tag";
  tag.textContent = item.source === "upload" ? "上传" : "本地";
  fn.appendChild(tag);
  fn.appendChild(document.createTextNode(item.filename));
  tdFile.appendChild(fn);
  tr.appendChild(tdFile);

  for (const field of ["track", "title", "artist", "album"]) {
    const td = document.createElement("td");
    td.className = `col-${field}`;
    const input = document.createElement("input");
    input.className = "cell-input";
    input.dataset.field = field;
    input.value = item[field] || "";
    input.placeholder = "—";
    input.addEventListener("input", () => onEdit(item.id, field, input.value));
    td.appendChild(input);
    tr.appendChild(td);
  }

  const tdStatus = document.createElement("td");
  tdStatus.className = "col-status";
  const status = document.createElement("span");
  status.className = "status";
  tdStatus.appendChild(status);
  tr.appendChild(tdStatus);

  const tdAct = document.createElement("td");
  tdAct.className = "col-act";
  if (item.source === "upload") {
    const dl = document.createElement("button");
    dl.className = "btn small";
    dl.title = "下载该文件";
    dl.textContent = "⬇";
    dl.addEventListener("click", () => window.open(`/api/download/${item.id}`, "_blank"));
    tdAct.appendChild(dl);
  }
  const del = document.createElement("button");
  del.className = "btn small";
  del.title = "移除";
  del.textContent = "✕";
  del.addEventListener("click", () => removeItem(item.id));
  tdAct.appendChild(del);
  tr.appendChild(tdAct);

  return tr;
}

function addItems(serverItems) {
  const rows = [];
  for (const it of serverItems) {
    const item = {
      id: it.id,
      filename: it.filename,
      source: it.source,
      track: it.existing?.track ?? "",
      title: it.existing?.title ?? "",
      artist: it.existing?.artist ?? "",
      album: it.existing?.album ?? "",
      statusText: it.existing_error ? `读标签失败: ${it.existing_error}` : "",
      statusCls: it.existing_error ? "err" : "",
      dirty: false,
    };
    state.items.push(item);
    rows.push(rowTemplate(item));
  }
  tbody.append(...rows);
  refreshEmpty();
  setStatusbar(`${state.items.length} 个文件`);
}

function getRow(id) {
  return tbody.querySelector(`tr[data-id="${id}"]`);
}
function getInput(id, field) {
  return getRow(id)?.querySelector(`input[data-field="${field}"]`);
}
function setStatus(id, text, cls = "") {
  const row = getRow(id);
  if (!row) return;
  const el = row.querySelector(".status");
  el.textContent = text;
  el.className = `status ${cls}`;
}
function onEdit(id, field, value) {
  const item = state.items.find((i) => i.id === id);
  if (!item) return;
  item[field] = value;
  item.dirty = true;
  const input = getInput(id, field);
  input?.classList.add("dirty");
  setStatus(id, "待保存", "");
}

function removeItem(id) {
  const idx = state.items.findIndex((i) => i.id === id);
  if (idx >= 0) state.items.splice(idx, 1);
  getRow(id)?.remove();
  refreshEmpty();
  setStatusbar(`${state.items.length} 个文件`);
}
function refreshEmpty() {
  $("#empty").classList.toggle("hidden", state.items.length > 0);
}

// ---------------------------------------------------------------- 添加/扫描/清空
const fileInput = $("#file-input");

async function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  setStatusbar("上传中…");
  try {
    const data = await api("/api/upload", { method: "POST", body: fd });
    addItems(data.items);
    if (data.errors?.length) toast(data.errors.join("\n"), 5000);
  } catch (e) {
    toast(e.message, 5000);
  }
}

$("#btn-add").addEventListener("click", () => fileInput.click());
$("#dropzone").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  uploadFiles([...fileInput.files]);
  fileInput.value = "";
});
const dz = $("#dropzone");
["dragenter", "dragover"].forEach((ev) =>
  dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.remove("dragover");
  })
);
dz.addEventListener("drop", (e) => uploadFiles([...e.dataTransfer.files]));

$("#btn-scan").addEventListener("click", async () => {
  const dir = prompt("输入工具所在机器上的目录路径（修改将直接写入原文件）：");
  if (!dir) return;
  try {
    const data = await api("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir }),
    });
    addItems(data.items);
    toast(`已添加 ${data.items.length} 个文件`);
  } catch (e) {
    toast(e.message, 5000);
  }
});

$("#btn-clear").addEventListener("click", () => {
  if (state.items.length && !confirm(`确定清空 ${state.items.length} 个文件？`)) return;
  state.items = [];
  tbody.innerHTML = "";
  refreshEmpty();
  setStatusbar("就绪");
});

// ---------------------------------------------------------------- AI 提取
$("#btn-ai").addEventListener("click", async () => {
  if (state.aiRunning) return;
  if (!state.items.length) return toast("列表为空");
  state.aiRunning = true;
  const btn = $("#btn-ai");
  btn.disabled = true;
  const progress = $("#ai-progress");
  progress.classList.remove("hidden");

  try {
    const { job_id } = await api("/api/ai/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: state.items.map((i) => i.id) }),
    });
    while (true) {
      const job = await api(`/api/ai/job/${job_id}`);
      progress.textContent = `提取中 ${job.done}/${job.total}…`;
      for (const [id, res] of Object.entries(job.results || {})) {
        const item = state.items.find((i) => i.id === id);
        if (!item) continue;
        item.track = res.track;
        item.title = res.title;
        item.dirty = true;
        getInput(id, "track").value = res.track;
        getInput(id, "title").value = res.title;
        getInput(id, "track").classList.add("dirty");
        getInput(id, "title").classList.add("dirty");
        if (res.source === "ai") {
          setStatus(id, "AI 已提取", "ai");
        } else {
          setStatus(id, `AI 失败(${res.error || "未知"})，已用本地推测`, "fallback");
        }
      }
      if (job.done >= job.total) break;
      await new Promise((r) => setTimeout(r, 700));
    }
    toast("AI 提取完成，请核对后保存");
  } catch (e) {
    toast(e.message, 5000);
  } finally {
    state.aiRunning = false;
    btn.disabled = false;
    progress.classList.add("hidden");
  }
});

// ---------------------------------------------------------------- 批量应用艺术家/专辑
$("#btn-apply").addEventListener("click", () => {
  const artist = $("#batch-artist").value.trim();
  const album = $("#batch-album").value.trim();
  if (!state.items.length) return toast("列表为空");
  for (const item of state.items) {
    item.artist = artist;
    item.album = album;
    item.dirty = true;
    const a = getInput(item.id, "artist");
    const b = getInput(item.id, "album");
    a.value = artist;
    b.value = album;
    a.classList.add("dirty");
    b.classList.add("dirty");
    setStatus(item.id, "待保存", "");
  }
  toast(`已应用 艺术家=[${artist}] 专辑=[${album}] 到全部 ${state.items.length} 行`);
});

// ---------------------------------------------------------------- 保存/下载
$("#btn-save").addEventListener("click", async () => {
  if (!state.items.length) return toast("列表为空");
  $("#btn-save").disabled = true;
  try {
    const payload = {
      items: state.items.map((i) => ({
        id: i.id,
        track: i.track.trim(),
        title: i.title.trim(),
        artist: i.artist.trim(),
        album: i.album.trim(),
      })),
    };
    const data = await api("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const byId = new Map(data.results.map((r) => [r.id, r]));
    for (const item of state.items) {
      const r = byId.get(item.id);
      item.dirty = false;
      if (r?.ok) {
        setStatus(item.id, "✓ 已保存", "ok");
      } else {
        setStatus(item.id, `保存失败: ${r?.error || "?"}`, "err");
      }
      for (const f of ["track", "title", "artist", "album"]) {
        const input = getInput(item.id, f);
        input?.classList.remove("dirty");
        if (input && item[f].trim()) input.classList.remove("missing");
      }
    }
    toast(`已保存 ${data.ok_count}/${state.items.length} 个文件`);
  } catch (e) {
    toast(e.message, 5000);
  } finally {
    $("#btn-save").disabled = false;
  }
});

$("#btn-zip").addEventListener("click", () => {
  window.open("/api/download_all", "_blank");
});

// ---------------------------------------------------------------- 设置
const modal = $("#modal");
function showGroup() {
  const p = $("#cfg-provider").value;
  $("#cfg-ollama").classList.toggle("hidden", p !== "ollama");
  $("#cfg-deepseek").classList.toggle("hidden", p !== "deepseek");
  $("#cfg-zhipu").classList.toggle("hidden", p !== "zhipu");
  $("#cfg-openrouter").classList.toggle("hidden", p !== "openrouter");
}
$("#btn-settings").addEventListener("click", async () => {
  const cfg = await api("/api/config");
  $("#cfg-provider").value = cfg.provider;
  $("#cfg-ollama-url").value = cfg.ollama.url;
  $("#cfg-ollama-model").value = cfg.ollama.model;
  $("#cfg-ds-url").value = cfg.deepseek.url;
  $("#cfg-ds-key").value = cfg.deepseek.api_key;
  $("#cfg-ds-model").value = cfg.deepseek.model;
  $("#cfg-zp-url").value = cfg.zhipu.url;
  $("#cfg-zp-key").value = cfg.zhipu.api_key;
  $("#cfg-zp-model").value = cfg.zhipu.model;
  $("#cfg-or-url").value = cfg.openrouter.url;
  $("#cfg-or-key").value = cfg.openrouter.api_key;
  $("#cfg-or-model").value = cfg.openrouter.model;
  $("#cfg-prompt").value = cfg.prompt || "";
  state.defaultPrompt = cfg.prompt_default || "";
  $("#try-filename").value = "01 - My Song.mp3";
  $("#try-result").textContent = "";
  $("#test-result").textContent = "";
  showGroup();
  modal.classList.remove("hidden");
});
$("#cfg-provider").addEventListener("change", showGroup);
$("#btn-cfg-cancel").addEventListener("click", () => modal.classList.add("hidden"));

function currentCfg() {
  return {
    provider: $("#cfg-provider").value,
    prompt: $("#cfg-prompt").value,
    ollama: {
      url: $("#cfg-ollama-url").value.trim(),
      model: $("#cfg-ollama-model").value.trim(),
    },
    deepseek: {
      url: $("#cfg-ds-url").value.trim(),
      model: $("#cfg-ds-model").value.trim(),
      api_key: $("#cfg-ds-key").value.trim(),
    },
    zhipu: {
      url: $("#cfg-zp-url").value.trim(),
      model: $("#cfg-zp-model").value.trim(),
      api_key: $("#cfg-zp-key").value.trim(),
    },
    openrouter: {
      url: $("#cfg-or-url").value.trim(),
      model: $("#cfg-or-model").value.trim(),
      api_key: $("#cfg-or-key").value.trim(),
    },
  };
}
$("#btn-prompt-reset").addEventListener("click", () => {
  $("#cfg-prompt").value = state.defaultPrompt || "";
});
$("#btn-test").addEventListener("click", async () => {
  const el = $("#test-result");
  el.textContent = "测试中…";
  el.className = "";
  try {
    const r = await api("/api/test_ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentCfg()),
    });
    el.textContent = r.message;
    el.className = r.ok ? "ok" : "err";
  } catch (e) {
    el.textContent = e.message;
    el.className = "err";
  }
});
$("#btn-try").addEventListener("click", async () => {
  const filename = $("#try-filename").value.trim();
  if (!filename) return toast("请先填写示例文件名");
  const btn = $("#btn-try");
  const el = $("#try-result");
  btn.disabled = true;
  el.textContent = "提取中…（AI 可能要等一会儿）";
  el.className = "";
  try {
    const r = await api("/api/ai/try", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, prompt: $("#cfg-prompt").value }),
    });
    const src = r.source === "ai" ? "AI" : "本地正则";
    el.textContent = `track="${r.track}"  title="${r.title}"  (来源: ${src}${r.error ? " · " + r.error : ""})`;
    el.className = r.source === "ai" ? "ok" : "err";
  } catch (e) {
    el.textContent = e.message;
    el.className = "err";
  } finally {
    btn.disabled = false;
  }
});
$("#btn-cfg-save").addEventListener("click", async () => {
  try {
    await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentCfg()),
    });
    modal.classList.add("hidden");
    toast("设置已保存");
  } catch (e) {
    toast(e.message);
  }
});

setStatusbar("就绪");
