const state = {
  config: null,
  videos: [],
  audios: [],
  projects: [],
  selectedVideo: null,
  selectedProject: null,
  selectedFilePath: null,
  polling: null,
};

function el(id) {
  return document.getElementById(id);
}

function bytes(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function setRunState(stateText) {
  el("serverState").textContent = stateText;
  el("runStatePill").textContent = stateText;
}

function setLinkedAudioLabel(path) {
  el("linkedAudioLabel").textContent = `当前附加音频：${path || "未设置"}`;
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

function renderVideos(videos) {
  state.videos = videos;
  const root = el("videoList");
  root.innerHTML = "";

  videos.forEach((video) => {
    const item = document.createElement("button");
    item.className = "video-item" + (state.selectedVideo?.path === video.path ? " active" : "");
    item.innerHTML = `
      <div><strong>${video.name}</strong></div>
      <div class="meta-row"><span>${video.external ? "外部导入" : "input目录"}</span><span>${bytes(video.size)}</span></div>
    `;
    item.addEventListener("click", () => {
      state.selectedVideo = video;
      el("selectedVideoName").textContent = video.name;
      el("selectedVideoMeta").textContent = `输入路径：${video.path}`;
      renderVideos(state.videos);
    });
    root.appendChild(item);
  });

  if (!state.selectedVideo && videos.length) {
    state.selectedVideo = videos[0];
    el("selectedVideoName").textContent = videos[0].name;
    el("selectedVideoMeta").textContent = `输入路径：${videos[0].path}`;
    renderVideos(videos);
  }
}

function renderStageFeed(history) {
  const root = el("stageFeed");
  root.innerHTML = "";
  history.slice().reverse().forEach((entry) => {
    const node = document.createElement("div");
    node.className = "stage-item";
    node.innerHTML = `
      <div><strong>${entry.stage}</strong></div>
      <div class="meta-row"><span>${JSON.stringify(entry.payload)}</span></div>
    `;
    root.appendChild(node);
  });
}

function renderQueue(queue) {
  const root = el("queueList");
  root.innerHTML = "";
  (queue || []).forEach((item, index) => {
    const node = document.createElement("div");
    node.className = "stage-item";
    node.innerHTML = `
      <div><strong>${index + 1}. ${item.name}</strong></div>
      <div class="meta-row"><span>${item.path}</span><span>${bytes(item.size || 0)}</span></div>
    `;
    root.appendChild(node);
  });
  if (!queue || !queue.length) {
    const empty = document.createElement("div");
    empty.className = "stage-item";
    empty.innerHTML = `<div><strong>队列为空</strong></div><div class="meta-row"><span>下载到队列或添加 Input 后会显示在这里。</span></div>`;
    root.appendChild(empty);
  }
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

function renderProjects(projects) {
  state.projects = projects;
  const list = el("projectList");
  list.innerHTML = "";

  projects.forEach((project) => {
    const wrapper = document.createElement("div");
    wrapper.className = "project-item" + (state.selectedProject?.path === project.path ? " active" : "");
    wrapper.innerHTML = `
      <div><strong>${project.name}</strong></div>
      <div class="meta-row"><span>${project.files.length} files</span></div>
    `;

    const fileList = document.createElement("div");
    fileList.className = "project-list";
    fileList.style.marginTop = "10px";

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

function renderState(payload) {
  const runState = payload.state.running ? "Running" : payload.state.current_stage;
  setRunState(runState);
  el("currentStageLabel").textContent = `当前阶段：${payload.state.current_stage}`;
  renderStageFeed(payload.state.history || []);
  renderQueue(payload.state.queue || []);
  renderProjects(payload.projects || []);
  if (payload.videos) renderVideos(payload.videos);
  if (payload.config) fillForm(payload.config);
}

function bootstrap() {
  fetch("/api/bootstrap")
    .then((res) => res.json())
    .then((payload) => {
      fillForm(payload.config);
      renderVideos(payload.videos);
      renderProjects(payload.projects);
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
    renderVideos(payload.videos);
    state.selectedVideo = payload.video;
    el("selectedVideoName").textContent = payload.video.name;
    el("selectedVideoMeta").textContent = `输入路径：${payload.video.path}`;
    renderVideos(payload.videos);
  });

  audioInput.addEventListener("change", async () => {
    const file = audioInput.files?.[0];
    if (!file) return;
    const payload = await uploadFile("/api/upload-audio", file);
    if (!payload.ok) return;
    el("audio_override_path").value = payload.audio.path;
    setLinkedAudioLabel(payload.audio.path);
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
  el("clearQueueBtn").addEventListener("click", () => {
    fetch("/api/queue/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((res) => res.json())
      .then((payload) => renderState({ state: payload.state, projects: state.projects, videos: state.videos }));
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
