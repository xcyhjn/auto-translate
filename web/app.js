const state = {
  config: null,
  videos: [],
  audios: [],
  projects: [],
  selectedVideo: null,
  selectedProject: null,
  selectedFilePath: null,
  polling: null,
  proxyStatus: null,
  selectedMediaInfo: null,
  mediaInspectToken: 0,
  lastErrorPayload: null,
};

const phaseLabels = {
  audio_extract: "音频提取",
  asr: "识别与打轴",
  translation: "翻译分块",
  burn: "烧录输出",
};

const phaseStatusLabels = {
  idle: "等待中",
  running: "进行中",
  complete: "已完成",
  error: "错误",
};

const summaryLabels = {
  path: "输出路径",
  input_path: "输入路径",
  audio_path: "音频路径",
  merged_path: "合并路径",
  output_dir: "输出目录",
  duration_seconds: "总时长",
  processed_seconds: "已处理",
  remaining_seconds: "剩余时间",
  size_bytes: "当前大小",
  estimated_final_size: "预计最终",
  count: "数量",
  chunk_index: "Chunk",
  chunk_total: "Chunk 总数",
  segment_count: "段数",
  progress: "进度",
  warnings: "警告",
  errors: "错误",
  speed: "编码速度",
  virtual_chunk_current: "块进度",
  virtual_chunk_total: "块总数",
  fallback_count: "回退条数",
};

function el(id) {
  return document.getElementById(id);
}

function bytes(size) {
  if (!size) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function seconds(value) {
  const total = Math.max(0, Math.round(Number(value || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function safeText(value) {
  return value || "";
}

function setRunState(stateText) {
  el("serverState").textContent = stateText;
  el("runStatePill").textContent = stateText;
}

function setLinkedAudioLabel(path) {
  el("linkedAudioLabel").textContent = `当前附加音频：${path || "未设置"}`;
}

function formatSummaryValue(key, value) {
  if (value == null || value === "") return "";
  if (key.endsWith("_seconds")) return seconds(value);
  if (key === "progress") return `${Number(value).toFixed(0)}%`;
  if (key === "size_bytes" || key === "estimated_final_size") return bytes(Number(value));
  if (key === "speed") return `${Number(value).toFixed(2)}x`;
  return String(value);
}

function showToast(message) {
  const toast = el("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.classList.add("hidden"), 180);
  }, 1800);
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    showToast("已复制");
  } catch {
    showToast("复制失败");
  }
}

function readFormConfig() {
  return {
    src_lang: el("src_lang").value,
    dst_lang: el("dst_lang").value,
    model: el("model").value,
    device: el("device").value,
    compute_type: el("compute_type").value,
    beam_size: Number(el("beam_size").value),
    translation_model: el("translation_model").value,
    translation_chunk_size: Number(el("translation_chunk_size").value),
    translation_retries: Number(el("translation_retries").value),
    openai_base_url: el("openai_base_url").value,
    audio_override_path: el("audio_override_path").value,
    preview_seconds: el("preview_seconds").value ? Number(el("preview_seconds").value) : null,
    load_existing_segments: el("load_existing_segments").checked,
    style: {
      zh_font_name: el("zh_font_name").value,
      zh_font_size: Number(el("zh_font_size").value),
      zh_margin_l: Number(el("zh_margin_l").value),
      zh_margin_r: Number(el("zh_margin_r").value),
      zh_margin_v: Number(el("zh_margin_v").value),
      en_font_name: el("en_font_name").value,
      en_font_size: Number(el("en_font_size").value),
      en_margin_l: Number(el("en_margin_l").value),
      en_margin_r: Number(el("en_margin_r").value),
      en_margin_v: Number(el("en_margin_v").value),
    },
  };
}

function fillForm(config) {
  state.config = config;
  el("src_lang").value = config.src_lang;
  el("dst_lang").value = config.dst_lang;
  el("model").value = config.model;
  el("device").value = config.device;
  el("compute_type").value = config.compute_type;
  el("beam_size").value = config.beam_size;
  el("translation_model").value = config.translation_model;
  el("translation_chunk_size").value = config.translation_chunk_size;
  el("translation_retries").value = config.translation_retries;
  el("openai_base_url").value = config.openai_base_url || "";
  el("audio_override_path").value = config.audio_override_path || "";
  el("preview_seconds").value = config.preview_seconds ?? "";
  el("load_existing_segments").checked = Boolean(config.load_existing_segments);

  const style = config.style || {};
  el("zh_font_name").value = style.zh_font_name || "Microsoft YaHei";
  el("zh_font_size").value = style.zh_font_size ?? 64;
  el("zh_margin_l").value = style.zh_margin_l ?? 90;
  el("zh_margin_r").value = style.zh_margin_r ?? 90;
  el("zh_margin_v").value = style.zh_margin_v ?? 94;
  el("en_font_name").value = style.en_font_name || "Arial";
  el("en_font_size").value = style.en_font_size ?? 40;
  el("en_margin_l").value = style.en_margin_l ?? 80;
  el("en_margin_r").value = style.en_margin_r ?? 100;
  el("en_margin_v").value = style.en_margin_v ?? 44;

  setLinkedAudioLabel(config.audio_override_path || "");
}

function renderMediaAlert() {
  const card = el("mediaAlertCard");
  const media = state.selectedMediaInfo;
  if (!state.selectedVideo || !media) {
    card.classList.add("hidden");
    card.innerHTML = "";
    return;
  }

  const rows = [`时长 ${seconds(media.duration_seconds || 0)}`];
  if (media.text_subtitle_streams || media.image_subtitle_streams) {
    rows.push(`字幕流 ${media.text_subtitle_streams || 0}/${media.image_subtitle_streams || 0}`);
  }

  if (media.has_audio) {
    card.className = "alert-card alert-ok";
    card.innerHTML = `
      <div class="alert-card-head">
        <strong>媒体检测通过</strong>
        <span>可直接运行</span>
      </div>
      <div class="alert-card-text">当前视频检测到可用音轨。</div>
      <div class="alert-card-meta">${rows.join(" · ")}</div>
    `;
    return;
  }

  card.className = "alert-card alert-warn";
  card.innerHTML = `
    <div class="alert-card-head">
      <strong>当前视频没有音轨</strong>
      <span>需要附加 MP3</span>
    </div>
    <div class="alert-card-text">这个视频不能直接提取音频。请先点击“追加 MP3”或“为当前视频追加 MP3”。</div>
    <div class="alert-card-meta">${rows.join(" · ")}</div>
  `;
}

async function inspectSelectedVideo() {
  const video = state.selectedVideo;
  if (!video) {
    state.selectedMediaInfo = null;
    renderMediaAlert();
    return;
  }

  const token = ++state.mediaInspectToken;
  try {
    const response = await fetch("/api/video-inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_path: video.path }),
    });
    const payload = await response.json();
    if (token !== state.mediaInspectToken) return;
    state.selectedMediaInfo = payload.media || null;
    renderMediaAlert();
  } catch {
    if (token !== state.mediaInspectToken) return;
    state.selectedMediaInfo = null;
    renderMediaAlert();
  }
}

function syncSelectedVideo(videos) {
  if (!videos.length) {
    state.selectedVideo = null;
    state.selectedMediaInfo = null;
    el("selectedVideoName").textContent = "未选择视频";
    el("selectedVideoMeta").textContent = "请添加视频后开始处理。";
    renderMediaAlert();
    return;
  }
  const previousPath = state.selectedVideo?.path;
  const matched = videos.find((video) => video.path === previousPath);
  state.selectedVideo = matched || videos[0];
  el("selectedVideoName").textContent = state.selectedVideo.name;
  el("selectedVideoMeta").textContent = `输入路径：${state.selectedVideo.path}`;
  if (state.selectedVideo.path !== previousPath || !state.selectedMediaInfo) {
    inspectSelectedVideo();
  }
}

function renderVideos(videos) {
  state.videos = videos;
  syncSelectedVideo(videos);
  const root = el("videoList");
  root.innerHTML = "";

  videos.forEach((video) => {
    const item = document.createElement("button");
    item.className = "video-item" + (state.selectedVideo?.path === video.path ? " active" : "");
    item.innerHTML = `
      <div><strong>${video.name}</strong></div>
      <div class="meta-row">
        <span>${video.managed ? "本次会话" : "初始输入"}</span>
        <span>${bytes(video.size)}</span>
      </div>
      <div class="path-note">${video.path}</div>
    `;
    item.addEventListener("click", () => {
      state.selectedVideo = video;
      state.selectedMediaInfo = null;
      syncSelectedVideo(state.videos);
      renderVideos(state.videos);
    });
    root.appendChild(item);
  });

  if (!videos.length) {
    root.innerHTML = `<div class="stage-item empty-card"><strong>暂无输入视频</strong><div class="meta-row"><span>点击“添加 Input”或下载视频后会出现在这里。</span></div></div>`;
  }
}

function renderStageFeed(history) {
  const root = el("stageFeed");
  root.innerHTML = "";
  const entries = history.slice().reverse();
  entries.forEach((entry) => {
    const node = document.createElement("div");
    node.className = "stage-item";
    const detail = Object.entries(entry.summary || {})
      .map(([key, value]) => {
        const label = summaryLabels[key] || key;
        return `<div class="summary-row"><span>${label}</span><strong>${safeText(formatSummaryValue(key, value))}</strong></div>`;
      })
      .join("");
    node.innerHTML = `
      <div class="stage-title-row">
        <strong>${entry.title || entry.stage}</strong>
        <span>${entry.stage}</span>
      </div>
      <div class="stage-description">${safeText(entry.description || "")}</div>
      <div class="summary-grid">${detail || `<div class="summary-row full"><span>摘要</span><strong>本阶段没有额外结构化字段。</strong></div>`}</div>
    `;
    root.appendChild(node);
  });
  if (!entries.length) {
    root.innerHTML = `<div class="stage-item empty-card"><strong>暂无运行日志</strong><div class="meta-row"><span>流程启动后会在这里展示结构化阶段摘要。</span></div></div>`;
  }
}

function renderQueue(queue) {
  const root = el("queueList");
  root.innerHTML = "";
  (queue || []).forEach((item, index) => {
    const node = document.createElement("div");
    node.className = "stage-item";
    node.innerHTML = `
      <div><strong>${index + 1}. ${item.name}</strong></div>
      <div class="meta-row"><span>${item.managed ? "本次会话" : "初始输入"}</span><span>${bytes(item.size || 0)}</span></div>
      <div class="path-note">${item.path}</div>
    `;
    root.appendChild(node);
  });
  if (!queue || !queue.length) {
    root.innerHTML = `<div class="stage-item empty-card"><strong>队列为空</strong><div class="meta-row"><span>下载到队列或添加 Input 后会显示在这里。</span></div></div>`;
  }
}

function renderChunkPanel(translationPhase) {
  const panel = el("chunkPanel");
  const chunks = translationPhase?.chunks || [];
  if (!chunks.length) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="chunk-panel-head">
      <strong>翻译 Chunk</strong>
      <span>${translationPhase.current || 0}/${translationPhase.total || chunks.length}</span>
    </div>
    <div class="chunk-grid">
      ${chunks
        .map((chunk) => {
          const badge = chunk.fallback_count ? `回退 ${chunk.fallback_count}` : chunk.segment_count ? `${chunk.segment_count} 段` : "";
          return `
            <div class="chunk-chip status-${chunk.status || "pending"}">
              <strong>${chunk.index}</strong>
              <span>${chunk.status || "pending"}</span>
              <em>${badge}</em>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderPhaseStatus(phaseStatus) {
  const root = el("phaseStatusList");
  root.innerHTML = "";

  Object.entries(phaseStatus || {}).forEach(([key, phase]) => {
    const card = document.createElement("div");
    card.className = "phase-card";
    const progress = Math.max(0, Math.min(100, Number(phase.progress || 0)));
    const stats = [];

    if (key === "audio_extract") {
      if (phase.processed_seconds || phase.duration_seconds) stats.push(`${seconds(phase.processed_seconds || 0)} / ${seconds(phase.duration_seconds || 0)}`);
      if (phase.size_bytes) stats.push(`输出 ${bytes(phase.size_bytes)}`);
    }

    if (key === "asr") {
      if (phase.current || phase.total) stats.push(`块 ${phase.current || 0}/${phase.total || 0}`);
      if (phase.segment_count) stats.push(`段数 ${phase.segment_count}`);
      if (phase.processed_seconds || phase.duration_seconds) stats.push(`${seconds(phase.processed_seconds || 0)} / ${seconds(phase.duration_seconds || 0)}`);
    }

    if (key === "translation") {
      if (phase.current || phase.total) stats.push(`Chunk ${phase.current || 0}/${phase.total || 0}`);
      if (phase.segment_count) stats.push(`总段数 ${phase.segment_count}`);
      if (phase.elapsed_seconds) stats.push(`最近耗时 ${seconds(phase.elapsed_seconds)}`);
      if (phase.fallback_count) stats.push(`回退 ${phase.fallback_count}`);
    }

    if (key === "burn") {
      if (phase.processed_seconds || phase.duration_seconds) stats.push(`${seconds(phase.processed_seconds || 0)} / ${seconds(phase.duration_seconds || 0)}`);
      if (phase.size_bytes) stats.push(`当前 ${bytes(phase.size_bytes)}`);
      if (phase.estimated_final_size) stats.push(`预计 ${bytes(phase.estimated_final_size)}`);
      if (phase.speed) stats.push(`速度 ${Number(phase.speed).toFixed(2)}x`);
      if (phase.remaining_seconds) stats.push(`剩余 ${seconds(phase.remaining_seconds)}`);
      stats.push(`${phase.encoder || "libx264"} · CRF ${phase.crf || 25} · ${phase.preset || "medium"}`);
    }

    card.innerHTML = `
      <div class="phase-head">
        <strong>${phaseLabels[key] || key}</strong>
        <span>${phaseStatusLabels[phase.status] || phase.status || "等待中"}</span>
      </div>
      <div class="phase-label">${phase.label || ""}</div>
      <div class="phase-progress"><div class="phase-progress-fill" style="width:${progress}%"></div></div>
      <div class="meta-row">
        <span>${progress.toFixed(0)}%</span>
        <span>${stats.join(" · ")}</span>
      </div>
    `;
    root.appendChild(card);
  });

  renderChunkPanel(phaseStatus?.translation);
}

function openFile(path, name) {
  state.selectedFilePath = path;
  el("previewTitle").textContent = name;
  const video = el("videoPreview");
  const text = el("textPreview");

  if (/\.(mp4|wav)$/i.test(path)) {
    const relative = path.split("output\\").pop().replaceAll("\\", "/");
    video.classList.remove("hidden");
    video.src = `/output/${encodeURI(relative)}`;
    text.textContent = "";
    return;
  }

  video.classList.add("hidden");
  fetch(`/api/file?path=${encodeURIComponent(path)}`)
    .then((res) => res.json())
    .then((payload) => {
      text.textContent = payload.content || "";
    });
}

function syncSelectedProject(projects) {
  if (!projects.length) {
    state.selectedProject = null;
    if (!state.selectedFilePath) {
      el("previewTitle").textContent = "文件预览";
      el("textPreview").textContent = "";
      el("videoPreview").classList.add("hidden");
      el("videoPreview").src = "";
    }
    return;
  }
  const matched = projects.find((project) => project.path === state.selectedProject?.path);
  state.selectedProject = matched || projects[0];
}

function renderProjects(projects) {
  state.projects = projects;
  syncSelectedProject(projects);
  const list = el("projectList");
  list.innerHTML = "";

  projects.forEach((project) => {
    const wrapper = document.createElement("div");
    wrapper.className = "project-item" + (state.selectedProject?.path === project.path ? " active" : "");
    wrapper.innerHTML = `
      <div><strong>${project.name}</strong></div>
      <div class="meta-row"><span>${project.files.length} files</span></div>
      <div class="path-note">${project.path}</div>
    `;

    const fileList = document.createElement("div");
    fileList.className = "project-list nested-project-list";

    project.files.forEach((file) => {
      const fileNode = document.createElement("button");
      fileNode.className = "file-item" + (state.selectedFilePath === file.path ? " active" : "");
      fileNode.innerHTML = `
        <div><strong>${file.name}</strong></div>
        <div class="meta-row"><span>${bytes(file.size)}</span></div>
      `;
      fileNode.addEventListener("click", (event) => {
        event.stopPropagation();
        openFile(file.path, file.name);
        renderProjects(state.projects);
      });
      fileList.appendChild(fileNode);
    });

    wrapper.addEventListener("click", () => {
      state.selectedProject = project;
      renderProjects(state.projects);
    });

    wrapper.appendChild(fileList);
    list.appendChild(wrapper);
  });
}

function renderErrorCard(lastError) {
  const card = el("errorCard");
  const text = el("errorCardText");
  if (!lastError?.message) {
    card.classList.add("hidden");
    text.textContent = "";
    state.lastErrorPayload = null;
    return;
  }
  state.lastErrorPayload = lastError;
  card.classList.remove("hidden");
  text.textContent = lastError.message;
  text.onclick = () => copyText(lastError.traceback || lastError.message);
}

function renderProxyStatus() {
  const card = el("proxyStatusCard");
  const proxy = state.proxyStatus;
  if (!proxy) {
    card.classList.add("hidden");
    card.innerHTML = "";
    return;
  }

  card.className = `proxy-status-card ${proxy.ok ? "proxy-ok" : "proxy-bad"}`;
  card.innerHTML = `
    <div class="proxy-status-head">
      <strong>${proxy.ok ? "代理检测通过" : "代理检测失败"}</strong>
      <span>${proxy.checked_at || ""}</span>
    </div>
    <div class="proxy-status-meta">代理：${proxy.proxy_url || "未设置"}</div>
    <div class="proxy-status-list">
      ${(proxy.results || [])
        .map((item) => {
          const detail = item.ok ? `状态 ${item.status_code}` : safeText(item.error || item.raw_error || "连接失败");
          return `<div class="proxy-status-row"><span>${item.name}</span><strong>${detail}</strong></div>`;
        })
        .join("")}
    </div>
  `;
}

function renderRuntime(runtime, lastError) {
  const title = runtime?.title || "等待中";
  const progress = Math.max(0, Math.min(100, Number(runtime?.overall_progress || 0)));
  const description = lastError?.message || runtime?.description || "等待开始新的任务。";
  setRunState(title);
  el("currentStageLabel").textContent = `当前阶段：${title}`;
  el("currentStageDescription").textContent = description;
  el("overallProgressLabel").textContent = `总进度 ${progress}%`;
  el("overallProgressFill").style.width = `${progress}%`;
  renderErrorCard(lastError);
}

function renderState(payload) {
  const runtime = payload.state.runtime || {};
  renderRuntime(runtime, payload.state.last_error);
  renderStageFeed(payload.state.history || []);
  renderQueue(payload.state.queue || []);
  renderPhaseStatus(payload.state.phase_status || {});
  renderProjects(payload.projects || []);
  if (payload.videos) renderVideos(payload.videos);
  if (payload.config) fillForm(payload.config);
  renderProxyStatus();
}

async function testProxy() {
  el("testProxyBtn").disabled = true;
  try {
    const response = await fetch("/api/proxy/status");
    const payload = await response.json();
    state.proxyStatus = payload.proxy || null;
    renderProxyStatus();
  } catch {
    state.proxyStatus = {
      ok: false,
      checked_at: "",
      proxy_url: "",
      results: [{ name: "proxy", error: "代理检测请求失败" }],
    };
    renderProxyStatus();
  } finally {
    el("testProxyBtn").disabled = false;
  }
}

function bootstrap() {
  fetch("/api/bootstrap")
    .then((res) => res.json())
    .then((payload) => {
      fillForm(payload.config);
      renderState(payload);
      startPolling();
    });
}

function startPolling() {
  if (state.polling) clearInterval(state.polling);
  state.polling = setInterval(() => {
    fetch("/api/state")
      .then((res) => res.json())
      .then((payload) => renderState(payload));
  }, 1800);
}

function bindTabs() {
  document.querySelectorAll(".tab, .nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = btn.dataset.panel;
      if (!panel) return;
      document.querySelectorAll(".tab").forEach((node) => node.classList.toggle("active", node.dataset.panel === panel));
      document.querySelectorAll(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.panel === panel));
      document.querySelectorAll(".workspace-panel").forEach((node) => node.classList.toggle("active", node.dataset.panel === panel));
    });
  });
}

function bindActions() {
  const uploadFile = async (endpoint, file) => {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: await file.arrayBuffer(),
    });
    return response.json();
  };

  const videoInput = el("videoFileInput");
  const audioInput = el("audioFileInput");

  const pickInput = () => {
    videoInput.value = "";
    videoInput.click();
  };

  const pickAudio = () => {
    audioInput.value = "";
    audioInput.click();
  };

  videoInput.addEventListener("change", async () => {
    const file = videoInput.files?.[0];
    if (!file) return;
    const payload = await uploadFile("/api/upload-video", file);
    if (!payload.ok) return;
    state.selectedVideo = payload.video;
    state.selectedMediaInfo = null;
    renderState(payload);
  });

  audioInput.addEventListener("change", async () => {
    const file = audioInput.files?.[0];
    if (!file) return;
    const payload = await uploadFile("/api/upload-audio", file);
    if (!payload.ok) return;
    el("audio_override_path").value = payload.audio.path;
    setLinkedAudioLabel(payload.audio.path);
    inspectSelectedVideo();
  });

  const openOutput = () => {
    const projectPath = state.selectedProject?.path || state.projects[0]?.path || null;
    fetch("/api/open-output", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    });
  };

  const runDownload = (runAfterDownload) => {
    const url = el("downloadUrlInput").value.trim();
    if (!url) return;
    if (state.proxyStatus && !state.proxyStatus.ok) {
      showToast("代理检测失败，请先修复代理");
      return;
    }
    const config = readFormConfig();
    fetch("/api/download-video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        run_after_download: runAfterDownload,
        config,
      }),
    });
  };

  const runPipeline = (previewSeconds = null) => {
    if (!state.selectedVideo) return;
    const config = readFormConfig();
    config.preview_seconds = previewSeconds;
    fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: state.selectedVideo.path,
        config,
      }),
    });
  };

  el("pickInputBtn").addEventListener("click", pickInput);
  el("pickInputInlineBtn").addEventListener("click", pickInput);
  el("pickAudioBtn").addEventListener("click", pickAudio);
  el("pickAudioInlineBtn").addEventListener("click", pickAudio);
  el("previewBtn").addEventListener("click", () => runPipeline(60));
  el("downloadOnlyBtn").addEventListener("click", () => runDownload(false));
  el("downloadAndRunBtn").addEventListener("click", () => runDownload(true));
  el("testProxyBtn").addEventListener("click", testProxy);
  el("copyErrorBtn").addEventListener("click", () => {
    const payload = state.lastErrorPayload;
    if (!payload) return;
    copyText(payload.traceback || payload.message);
  });
  el("clearQueueBtn").addEventListener("click", () => {
    fetch("/api/queue/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((res) => res.json())
      .then((payload) => {
        state.selectedProject = null;
        state.selectedFilePath = null;
        state.selectedVideo = null;
        state.selectedMediaInfo = null;
        renderState(payload);
      });
  });
  el("openOutputBtn").addEventListener("click", openOutput);
  el("openOutputInlineBtn").addEventListener("click", openOutput);

  el("saveConfigBtn").addEventListener("click", () => {
    const config = readFormConfig();
    fetch("/api/save-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
  });

  el("runBtn").addEventListener("click", () => runPipeline(null));
}

bindTabs();
bindActions();
bootstrap();
