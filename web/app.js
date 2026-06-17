const state = {
  config: null,
  workflowProfiles: [],
  activePromptProfile: "",
  activeDatasetProfile: null,
  videos: [],
  audios: [],
  projects: [],
  jobs: [],
  activeJob: null,
  inputListCollapsed: true,
  expandedProjectPath: null,
  selectedVideo: null,
  selectedProject: null,
  selectedFilePath: null,
  selectedFileProjectPath: null,
  selectedVideoProjectPath: null,
  selectedVideoProject: null,
  polling: null,
  proxyStatus: null,
  idmStatus: null,
  youtubeMeta: null,
  bilibiliDuplicate: null,
  localFeedbackSummary: null,
  localFeedbackAction: null,
  feedbackReview: {
    kind: "style",
    status: "pending",
    loading: false,
    records: [],
    selectedRecordId: "",
    selectedRecordIds: [],
    detailRecordId: "",
    detailLoading: false,
    detail: null,
    bulkBusy: false,
    message: "",
  },
  learningQualityAction: {
    status: "idle",
    action: "",
    message: "",
  },
  localFeedbackAbEval: {
    preview: null,
    report: null,
    status: "idle",
    message: "",
    sampleKind: "mixed",
    sampleCount: 5,
  },
  localFeedbackImpact: null,
  learningGuidelinesExpanded: false,
  organizePreview: null,
  learningQuality: null,
  selectedMediaInfo: null,
  mediaInspectToken: 0,
  lastErrorPayload: null,
  runtime: null,
  openaiRuntime: null,
  flowControl: {
    pause_requested: false,
    paused: false,
    pause_reason: "",
    pause_stage: "",
  },
  pollCount: 0,
  formDirty: false,
  configSaveState: "saved",
  entityArtifacts: {
    projectPath: null,
    signature: "",
    token: 0,
    loading: false,
    metrics: null,
    reviewRows: [],
    qaRows: [],
    normalizedSegments: [],
    decisions: null,
    missing: [],
    errors: [],
  },
  segmentationArtifacts: {
    projectPath: null,
    signature: "",
    token: 0,
    loading: false,
    metrics: null,
    allocation: null,
    repair: null,
    missing: [],
    errors: [],
  },
  seenListItems: {
    videos: new Set(),
    stage: new Set(),
    queue: new Set(),
    jobs: new Set(),
    phases: new Set(),
    projects: new Set(),
    statusCards: new Set(),
  },
};

const DEFAULT_UI_CONFIG = {
  workflow_profile: "en_to_zh_default",
  src_lang: "en",
  dst_lang: "zh-Hans",
  model: "distil-large-v3",
  asr_audio_mode: "off",
  asr_audio_gain_db: 6.0,
  asr_vad_mode: "auto",
  device: "cuda",
  compute_type: "float16",
  beam_size: 5,
  translation_model: "gpt-5.4",
  prompt_profile: "en_zh_natural_subtitle",
  dataset_profile: "en_zh/general",
  subtitle_mode: "bilingual_source_reference",
  source_reference_label: "en",
  translation_prompt:
    "Prioritize faithful meaning over literal wording. Preserve casual spoken tone, hesitation, intimacy, jokes, sarcasm, and implied meaning when present. Translate spoken English into natural Simplified Chinese subtitles, not formal written Chinese. Keep the line concise and subtitle-friendly; do not add explanations.",
  translation_chunk_size: 24,
  translation_retries: 4,
  openai_base_url: "",
  proxy_url: "",
  audio_override_path: "",
  preview_seconds: null,
  load_existing_segments: false,
  force_retranslate_existing_segments: false,
  skip_burn: false,
  repair_high_risk_spans: true,
  span_translation_max_spans: 4,
  span_translation_max_segments: 4,
  span_translation_max_duration: 12.0,
  span_translation_min_risk_score: 10,
  span_repair_max_spans: 12,
  semantic_zh_allocation_enabled: true,
  semantic_zh_allocation_max_spans: 16,
  short_complete_sentence_display_grouping: true,
  english_residue_validation_enabled: true,
  english_residue_preserve_threshold: 85,
  english_residue_review_threshold: 70,
  enable_ai_display_rewrite: false,
  enable_local_translation_feedback: false,
  display_rewrite_max_ai_segments: 12,
  bootstrap_entity_decisions: "high_confidence_only",
  download_backend: "auto",
  idm_exe_path: "",
  idm_output_dir: "",
  idm_wait_timeout_seconds: 1800,
  idm_stable_seconds: 8,
  download_keep_intermediate_files: false,
  download_manual_fallback: true,
  style: {
    zh_font_name: "Maple Mono NF CN",
    zh_font_size: 64,
    zh_primary_color: "#FFF2A6",
    zh_primary_opacity: 100,
    zh_outline_color: "#202020",
    zh_outline_opacity: 45,
    zh_shadow_color: "#000000",
    zh_shadow_opacity: 35,
    zh_outline_width: 1.8,
    zh_shadow_depth: 0.4,
    zh_margin_l: 90,
    zh_margin_r: 90,
    zh_margin_v: 94,
    zh_wrap_trigger_chars: 32,
    zh_max_chars_per_line: 28,
    zh_max_lines: 2,
    en_font_name: "Maple Mono NF CN",
    en_font_size: 40,
    en_margin_l: 80,
    en_margin_r: 100,
    en_margin_v: 44,
    en_max_single_line_chars: 78,
    en_max_split_parts: 3,
    min_split_duration: 0.9,
    reference_mode: "compact",
  },
};

function normalizeUiConfig(config) {
  const incoming = config && typeof config === "object" ? config : {};
  const incomingStyle = incoming.style && typeof incoming.style === "object" ? incoming.style : {};
  return {
    ...DEFAULT_UI_CONFIG,
    ...incoming,
    style: {
      ...DEFAULT_UI_CONFIG.style,
      ...incomingStyle,
    },
  };
}

function syncLocalConfigFromForm() {
  state.config = normalizeUiConfig(readFormConfig());
  renderWorkflowSummary();
  renderAdvancedStrategySummary();
  renderCommandContext();
  renderEntityReviewPanel();
}

function markConfigDirty() {
  state.formDirty = true;
  syncLocalConfigFromForm();
  state.configSaveState = "dirty";
  renderConfigSaveState();
}

function clearConfigDirty(config = null) {
  if (config) {
    state.config = normalizeUiConfig(config);
  }
  state.formDirty = false;
  state.configSaveState = "saved";
  renderConfigSaveState();
}

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

const ACTIVE_JOB_STATUSES = new Set(["queued", "running", "paused", "cancel_requested"]);

const jobStatusLabels = {
  queued: "排队中",
  running: "运行中",
  paused: "已暂停",
  cancel_requested: "取消中",
  succeeded: "已完成",
  succeeded_with_qa_issues: "已完成，QA 有风险",
  failed: "失败",
  cancelled: "已取消",
};

const summaryLabels = {
  path: "输出路径",
  input_path: "输入路径",
  audio_path: "音频路径",
  source_audio_path: "原始音频",
  enhanced_audio_path: "增强音频",
  merged_path: "合并路径",
  output_dir: "输出目录",
  audio_mode: "音频模式",
  enhancement_mode: "增强模式",
  vad_mode: "VAD 策略",
  vad_filter: "VAD 开关",
  gain_db: "增益 dB",
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
  span_count: "Span 数",
  high_count: "高风险",
  medium_count: "中风险",
  low_count: "低风险",
  needs_ai_repair_count: "待 AI 修复",
  review_count: "待人工复核",
  candidate_count: "候选 Span",
  attempted_count: "尝试修复",
  repaired_segment_count: "已修复段数",
  failed_count: "修复失败",
  rejected_count: "已拒绝修复",
  eligible_span_count: "可修复 Span",
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

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0%";
  const normalized = number <= 1 ? number * 100 : number;
  return `${normalized.toFixed(normalized >= 10 ? 0 : 1)}%`;
}

function yesNo(value) {
  return value ? "开" : "关";
}

function safeText(value) {
  return value || "";
}

function normalizeBootstrapMode(value) {
  if (value === true) return "always";
  if (value === false) return "off";
  const normalized = String(value || "high_confidence_only").trim().toLowerCase();
  return ["off", "always", "high_confidence_only"].includes(normalized)
    ? normalized
    : "high_confidence_only";
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const BUTTON_SVGS = {
  play: '<path d="M8 5v14l11-7z"/>',
  pause: '<path d="M7 5v14M17 5v14"/>',
  folder: '<path d="M3 7h6l2 2h10v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 7V6a2 2 0 0 1 2-2h4l2 2"/>',
  save: '<path d="M5 4h11l3 3v13H5z"/><path d="M7 4v6h8V4"/><path d="M8 20h8"/>',
  upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M5 20h14"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  copy: '<rect x="9" y="9" width="10" height="10" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/>',
  alert: '<path d="M10.3 3.5 1.7 18a2 2 0 0 0 1.7 3h17.2a2 2 0 0 0 1.7-3L13.7 3.5a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.9-3"/><path d="M4 5v4h4"/><path d="M4 13a8 8 0 0 0 14.9 3"/><path d="M20 19v-4h-4"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/><path d="M10 11v5M14 11v5"/>',
  scan: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  image: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m7 15 3-3 2 2 3-4 4 5"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="7" cy="18" r="3"/><circle cx="19" cy="16" r="3"/>',
  spark: '<path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8z"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
};

function buttonSvg(name) {
  const path = BUTTON_SVGS[name];
  if (!path) return "";
  return `<svg class="button-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${path}</svg>`;
}

function setButtonContent(target, iconName, label) {
  const node = typeof target === "string" ? el(target) : target;
  if (!node) return;
  const text = label ?? node.dataset.label ?? node.textContent.trim();
  if (!node.dataset.label) node.dataset.label = text;
  node.classList.add("icon-btn");
  node.innerHTML = `${buttonSvg(iconName)}<span class="button-label">${escapeHtml(text)}</span>`;
}

function decorateStaticButtons() {
  [
    ["runBtn", "play"],
    ["previewBtn", "play"],
    ["pauseFlowBtn", "pause"],
    ["resumeFlowBtn", "play"],
    ["cancelJobBtn", "alert"],
    ["pickInputBtn", "upload"],
    ["pickAudioBtn", "music"],
    ["openOutputBtn", "folder"],
    ["clearQueueBtn", "trash"],
    ["saveConfigBtn", "save"],
    ["saveConfigBottomBtn", "save"],
    ["pickInputInlineBtn", "upload"],
    ["pickAudioInlineBtn", "music"],
    ["openYoutubeOutputBtn", "folder"],
    ["openOutputInlineBtn", "folder"],
    ["openInputBtn", "folder"],
    ["scanInputBtn", "scan"],
    ["downloadOnlyBtn", "download"],
    ["downloadAndRunBtn", "play"],
    ["testProxyBtn", "alert"],
    ["checkIdmBtn", "scan"],
    ["fetchYoutubeInfoBtn", "download"],
    ["fetchYoutubeCoverBtn", "image"],
    ["bilibiliDuplicateSearchBtn", "scan"],
    ["rebuildPaddedCoverBtn", "refresh"],
    ["copyErrorBtn", "copy"],
    ["applyRussianWorkflowBtn", "spark"],
    ["collectStyleFeedbackBtn", "spark"],
    ["collectSpanFeedbackBtn", "spark"],
    ["learnStyleBtn", "spark"],
    ["reburnFromInputBtn", "refresh"],
    ["reburnFromAssBtn", "refresh"],
  ].forEach(([id, icon]) => setButtonContent(id, icon));
}

function revealNode(node, index = 0) {
  if (!node) return;
  node.classList.add("list-enter");
  node.style.transitionDelay = `${Math.min(index, 8) * 40}ms`;
  requestAnimationFrame(() => node.classList.add("is-visible"));
}

function revealNewNode(group, key, node, index = 0) {
  const bucket = state.seenListItems[group];
  if (!bucket || !key) {
    revealNode(node, index);
    return;
  }
  if (bucket.has(key)) {
    node.classList.add("is-visible");
    return;
  }
  bucket.add(key);
  revealNode(node, index);
}

function revealChildren(root, selector = ".list-enter") {
  if (!root) return;
  root.querySelectorAll(selector).forEach((node, index) => revealNode(node, index));
}

function revealMotionNodes() {
  const nodes = Array.from(document.querySelectorAll(".motion-enter"));
  nodes.slice(0, 8).forEach((node, index) => {
    node.style.transitionDelay = `${index * 40}ms`;
    requestAnimationFrame(() => node.classList.add("is-visible"));
  });
}

function setRunState(stateText, runState = "idle") {
  el("serverState").textContent = stateText;
  el("runStatePill").textContent = stateText;
  const commandState = el("commandRunState");
  if (commandState) commandState.textContent = stateText;
  document.body.dataset.runState = runState || "idle";
}

function setTaskButtonsDisabled(disabled) {
  ["runBtn", "previewBtn", "downloadOnlyBtn", "downloadAndRunBtn"].forEach((id) => {
    const node = el(id);
    if (node) node.disabled = disabled;
  });
  renderFlowControlButtons();
  renderJobControls();
}

function taskIsBusy(runtime) {
  return !["idle", "complete", "error", "recovered_state"].includes(String(runtime?.stage_key || "idle"));
}

function normalizeRunState(runtime, lastError = null) {
  const flow = state.flowControl || {};
  if (lastError?.message) return "error";
  if (flow.paused) return "paused";
  if (flow.pause_requested) return "running";
  const key = String(runtime?.stage_key || "idle");
  if (["error", "failed"].includes(key)) return "error";
  if (["idle", "complete", "recovered_state"].includes(key)) return key;
  return "running";
}

function jobIsActive(job = state.activeJob) {
  return ACTIVE_JOB_STATUSES.has(String(job?.status || ""));
}

function renderFlowControlButtons() {
  const pauseBtn = el("pauseFlowBtn");
  const resumeBtn = el("resumeFlowBtn");
  if (!pauseBtn || !resumeBtn) return;
  const busy = taskIsBusy(state.runtime);
  const flow = state.flowControl || {};
  const waiting = Boolean(flow.pause_requested || flow.paused);
  pauseBtn.disabled = !busy || waiting;
  resumeBtn.disabled = !waiting;
  resumeBtn.classList.toggle("hidden", !waiting);
}

function renderJobControls() {
  const cancelBtn = el("cancelJobBtn");
  if (!cancelBtn) return;
  cancelBtn.disabled = !jobIsActive();
}

function scrollToWorkspaceDetails() {
  el("workspaceDetails")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function findProjectForSelectedVideo() {
  const videoPath = state.selectedVideo?.path || "";
  if (!videoPath) return null;
  const normalizedVideoPath = String(videoPath).toLowerCase();
  return (
    state.projects.find((project) => {
      const inputVideo = String(project.input_video || "").toLowerCase();
      const inputVideoName = String(project.input_video_name || "").toLowerCase();
      return inputVideo === normalizedVideoPath || inputVideoName === normalizedVideoPath.split("\\").pop();
    }) || null
  );
}

function renderInputAssStatus() {
  const statusNode = el("inputAssStatus");
  const buttonNode = el("reburnFromInputBtn");
  if (!statusNode || !buttonNode) return;

  const project = state.selectedVideoProject;
  const busy = taskIsBusy(state.runtime);
  buttonNode.disabled = busy || !project?.ass_path;

  if (!state.selectedVideo) {
    statusNode.textContent = "请先选择一个 input 视频";
    statusNode.className = "input-ass-status idle";
    return;
  }
  if (!project) {
    statusNode.textContent = "当前 input 还没有对应输出项目";
    statusNode.className = "input-ass-status idle";
    return;
  }
  if (!project.ass_path) {
    statusNode.textContent = "对应项目里还没有双语 ASS";
    statusNode.className = "input-ass-status idle";
    return;
  }
  if (!project.burned_video_path) {
    statusNode.textContent = "已找到双语 ASS，尚未烧录成视频";
    statusNode.className = "input-ass-status dirty";
    return;
  }

  const assTime = Number(project.ass_mtime_ts || 0);
  const burnedTime = Number(project.burned_video_mtime_ts || 0);
  if (assTime > burnedTime + 0.001) {
    statusNode.textContent = "双语 ASS 已修改，建议重新烧录";
    statusNode.className = "input-ass-status dirty";
    return;
  }
  statusNode.textContent = "当前烧录视频已和双语 ASS 同步";
  statusNode.className = "input-ass-status saved";
}

function updateFileActionButtons() {
  const isAss = /\.ass$/i.test(state.selectedFilePath || "");
  const reburnFromAssBtn = el("reburnFromAssBtn");
  if (reburnFromAssBtn) {
    reburnFromAssBtn.disabled = !isAss || taskIsBusy(state.runtime);
  }
  const collectStyleFeedbackBtn = el("collectStyleFeedbackBtn");
  if (collectStyleFeedbackBtn) {
    collectStyleFeedbackBtn.disabled = !isAss;
  }
  const collectSpanFeedbackBtn = el("collectSpanFeedbackBtn");
  if (collectSpanFeedbackBtn) {
    collectSpanFeedbackBtn.disabled = !isAss;
  }
  el("learnStyleBtn").disabled = !isAss;
  renderInputAssStatus();
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

function inferToastType(message, type = "") {
  if (type) return type;
  const text = String(message || "");
  if (/失败|错误|报错|未通过|不可用/.test(text)) return "error";
  if (/警告|风险|请先|需要|未保存/.test(text)) return "warn";
  if (/已|成功|通过|完成|保存|复制|添加|获取|开始/.test(text)) return "success";
  return "info";
}

function showToast(message, type = "") {
  const toast = el("toast");
  toast.textContent = message;
  toast.classList.remove("success", "warn", "error", "info");
  toast.classList.add(inferToastType(message, type));
  toast.classList.remove("hidden");
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.classList.add("hidden"), 180);
  }, 1800);
}

function renderConfigSaveState() {
  const node = el("configSaveState");
  if (!node) return;
  if (state.configSaveState === "saving") {
    node.textContent = "正在保存当前配置";
    node.className = "config-save-state saving";
    const commandStateSaving = el("commandConfigState");
    if (commandStateSaving) commandStateSaving.textContent = "正在保存当前配置";
    return;
  }
  const dirty = state.configSaveState === "dirty";
  node.textContent = dirty ? "当前配置未保存" : "当前配置已保存";
  node.className = `config-save-state ${dirty ? "dirty" : "saved"}`;
  const commandState = el("commandConfigState");
  if (commandState) commandState.textContent = node.textContent;
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

function normalizeHexColor(value, fallback = "#FFFFFF") {
  let raw = String(value || "").trim();
  if (raw.startsWith("#")) raw = raw.slice(1);
  if (/^[0-9a-fA-F]{3}$/.test(raw)) {
    raw = raw.split("").map((ch) => ch + ch).join("");
  }
  if (!/^[0-9a-fA-F]{6}$/.test(raw)) {
    raw = fallback.replace("#", "");
  }
  return `#${raw.toUpperCase()}`;
}

function clampNumber(value, min, max, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function alphaFromOpacity(opacity) {
  return clampNumber(opacity, 0, 100, 100) / 100;
}

function rgbaFromHex(hex, opacity) {
  const normalized = normalizeHexColor(hex).replace("#", "");
  const red = parseInt(normalized.slice(0, 2), 16);
  const green = parseInt(normalized.slice(2, 4), 16);
  const blue = parseInt(normalized.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alphaFromOpacity(opacity).toFixed(2)})`;
}

function readColorField(id, fallback) {
  return normalizeHexColor(el(id)?.value, fallback);
}

function readOpacityField(id, fallback) {
  return clampNumber(el(id)?.value, 0, 100, fallback);
}

function setColorField(id, value, fallback) {
  const color = normalizeHexColor(value, fallback);
  const picker = el(id);
  const hex = el(`${id}_hex`);
  if (picker) picker.value = color;
  if (hex) hex.value = color;
}

function setOpacityField(id, value, fallback) {
  const opacity = clampNumber(value, 0, 100, fallback);
  const input = el(id);
  const output = el(`${id}_value`);
  if (input) input.value = opacity;
  if (output) output.value = `${Math.round(opacity)}%`;
}

function syncColorInputs(id, fallback) {
  const picker = el(id);
  const hex = el(`${id}_hex`);
  if (!picker || !hex) return;
  const apply = (value) => {
    setColorField(id, value, fallback);
    updateSubtitleStylePreview();
    markConfigDirty();
  };
  picker.addEventListener("input", () => apply(picker.value));
  hex.addEventListener("input", () => {
    if (/^#?[0-9a-fA-F]{0,6}$/.test(hex.value.trim())) {
      hex.value = hex.value.toUpperCase();
    }
  });
  hex.addEventListener("change", () => apply(hex.value));
}

function syncOpacityInput(id, fallback) {
  const input = el(id);
  if (!input) return;
  input.addEventListener("input", () => {
    setOpacityField(id, input.value, fallback);
    updateSubtitleStylePreview();
    markConfigDirty();
  });
}

function updateSubtitleStylePreview() {
  const preview = el("zhStylePreview");
  if (!preview) return;
  const style = {
    fontName: el("zh_font_name")?.value || "Maple Mono NF CN",
    fontSize: clampNumber(el("zh_font_size")?.value, 24, 96, 64),
    primaryColor: readColorField("zh_primary_color", "#FFF2A6"),
    primaryOpacity: readOpacityField("zh_primary_opacity", 100),
    outlineColor: readColorField("zh_outline_color", "#202020"),
    outlineOpacity: readOpacityField("zh_outline_opacity", 45),
    shadowColor: readColorField("zh_shadow_color", "#000000"),
    shadowOpacity: readOpacityField("zh_shadow_opacity", 35),
    outlineWidth: clampNumber(el("zh_outline_width")?.value, 0, 12, 1.8),
    shadowDepth: clampNumber(el("zh_shadow_depth")?.value, 0, 12, 0.4),
  };
  preview.style.fontFamily = `"${style.fontName}", "Microsoft YaHei", sans-serif`;
  preview.style.fontSize = `${Math.round(style.fontSize * 0.42)}px`;
  preview.style.color = rgbaFromHex(style.primaryColor, style.primaryOpacity);
  preview.style.webkitTextStroke = `${style.outlineWidth}px ${rgbaFromHex(style.outlineColor, style.outlineOpacity)}`;
  preview.style.textShadow = `${style.shadowDepth * 3}px ${style.shadowDepth * 3}px ${Math.max(2, style.shadowDepth * 4)}px ${rgbaFromHex(style.shadowColor, style.shadowOpacity)}`;
}

function readFormConfig() {
  return {
    workflow_profile: el("workflow_profile")?.value || "en_to_zh_default",
    src_lang: el("src_lang").value,
    dst_lang: el("dst_lang").value,
    model: el("model").value,
    asr_audio_mode: el("asr_audio_mode").value,
    asr_audio_gain_db: Number(el("asr_audio_gain_db").value || 6.0),
    asr_vad_mode: el("asr_vad_mode").value,
    device: el("device").value,
    compute_type: el("compute_type").value,
    beam_size: Number(el("beam_size").value),
    translation_model: el("translation_model").value,
    prompt_profile: el("prompt_profile")?.value || "",
    dataset_profile: el("dataset_profile")?.value || "",
    subtitle_mode: el("subtitle_mode")?.value || "bilingual_source_reference",
    source_reference_label: el("source_reference_label")?.value || "",
    translation_prompt: el("translation_prompt").value,
    translation_chunk_size: Number(el("translation_chunk_size").value),
    translation_retries: Number(el("translation_retries").value),
    openai_base_url: el("openai_base_url").value,
    proxy_url: el("proxy_url")?.value || "",
    audio_override_path: el("audio_override_path").value,
    preview_seconds: el("preview_seconds").value ? Number(el("preview_seconds").value) : null,
    load_existing_segments: el("load_existing_segments").checked,
    force_retranslate_existing_segments: el("force_retranslate_existing_segments").checked,
    skip_burn: el("skip_burn").checked,
    repair_high_risk_spans: el("repair_high_risk_spans").checked,
    span_translation_max_spans: Number(el("span_translation_max_spans")?.value || 4),
    span_translation_max_segments: Number(el("span_translation_max_segments")?.value || 4),
    span_translation_max_duration: Number(el("span_translation_max_duration")?.value || 12.0),
    span_translation_min_risk_score: Number(el("span_translation_min_risk_score")?.value || 10),
    span_repair_max_spans: Number(el("span_repair_max_spans").value || 12),
    semantic_zh_allocation_enabled: el("semantic_zh_allocation_enabled")?.checked !== false,
    semantic_zh_allocation_max_spans: Number(el("semantic_zh_allocation_max_spans")?.value || 16),
    short_complete_sentence_display_grouping: el("short_complete_sentence_display_grouping")?.checked !== false,
    english_residue_validation_enabled: state.config?.english_residue_validation_enabled !== false,
    english_residue_preserve_threshold: Number(state.config?.english_residue_preserve_threshold ?? 85),
    english_residue_review_threshold: Number(state.config?.english_residue_review_threshold ?? 70),
    enable_ai_display_rewrite: el("enable_ai_display_rewrite").checked,
    enable_local_translation_feedback: el("enable_local_translation_feedback")?.checked === true,
    display_rewrite_max_ai_segments: Number(el("display_rewrite_max_ai_segments").value || 12),
    bootstrap_entity_decisions: normalizeBootstrapMode(el("bootstrap_entity_decisions")?.value),
    download_backend: el("download_backend").value,
    idm_exe_path: el("idm_exe_path").value,
    idm_output_dir: el("idm_output_dir").value,
    idm_wait_timeout_seconds: Number(el("idm_wait_timeout_seconds").value || 1800),
    idm_stable_seconds: 8,
    download_keep_intermediate_files: false,
    download_manual_fallback: true,
    style: {
      zh_font_name: el("zh_font_name").value,
      zh_font_size: Number(el("zh_font_size").value),
      zh_primary_color: readColorField("zh_primary_color", "#FFF2A6"),
      zh_primary_opacity: readOpacityField("zh_primary_opacity", 100),
      zh_outline_color: readColorField("zh_outline_color", "#202020"),
      zh_outline_opacity: readOpacityField("zh_outline_opacity", 45),
      zh_shadow_color: readColorField("zh_shadow_color", "#000000"),
      zh_shadow_opacity: readOpacityField("zh_shadow_opacity", 35),
      zh_outline_width: Number(el("zh_outline_width").value || 1.8),
      zh_shadow_depth: Number(el("zh_shadow_depth").value || 0.4),
      zh_margin_l: Number(el("zh_margin_l").value),
      zh_margin_r: Number(el("zh_margin_r").value),
      zh_margin_v: Number(el("zh_margin_v").value),
      zh_wrap_trigger_chars: Number(el("zh_wrap_trigger_chars").value || 32),
      zh_max_chars_per_line: Number(el("zh_max_chars_per_line").value || 28),
      zh_max_lines: Number(el("zh_max_lines").value || 2),
      en_font_name: el("en_font_name").value,
      en_font_size: Number(el("en_font_size").value),
      en_margin_l: Number(el("en_margin_l").value),
      en_margin_r: Number(el("en_margin_r").value),
      en_margin_v: Number(el("en_margin_v").value),
      en_max_single_line_chars: Number(el("en_max_single_line_chars").value || 78),
      en_max_split_parts: Number(el("en_max_split_parts").value || 3),
      min_split_duration: Number(el("min_split_duration").value || 0.9),
      reference_mode: el("reference_mode").value || "compact",
    },
  };
}

function fillForm(config) {
  const normalized = normalizeUiConfig(config);
  state.config = normalized;
  config = normalized;
  if (el("workflow_profile")) el("workflow_profile").value = config.workflow_profile || "en_to_zh_default";
  if (el("prompt_profile")) el("prompt_profile").value = config.prompt_profile || "";
  if (el("dataset_profile")) el("dataset_profile").value = config.dataset_profile || "";
  if (el("subtitle_mode")) el("subtitle_mode").value = config.subtitle_mode || "bilingual_source_reference";
  if (el("source_reference_label")) el("source_reference_label").value = config.source_reference_label || config.src_lang || "";
  el("src_lang").value = config.src_lang;
  el("dst_lang").value = config.dst_lang;
  el("model").value = config.model;
  el("asr_audio_mode").value = config.asr_audio_mode || "off";
  el("asr_audio_gain_db").value = config.asr_audio_gain_db ?? 6.0;
  el("asr_vad_mode").value = config.asr_vad_mode || "auto";
  el("device").value = config.device;
  el("compute_type").value = config.compute_type;
  el("beam_size").value = config.beam_size;
  el("translation_model").value = config.translation_model;
  el("translation_prompt").value = config.translation_prompt || "";
  el("translation_chunk_size").value = config.translation_chunk_size;
  el("translation_retries").value = config.translation_retries;
  el("openai_base_url").value = config.openai_base_url || "";
  if (el("proxy_url")) el("proxy_url").value = config.proxy_url || "";
  el("audio_override_path").value = config.audio_override_path || "";
  el("preview_seconds").value = config.preview_seconds ?? "";
  el("load_existing_segments").checked = Boolean(config.load_existing_segments);
  el("force_retranslate_existing_segments").checked = Boolean(config.force_retranslate_existing_segments);
  el("skip_burn").checked = Boolean(config.skip_burn);
  el("repair_high_risk_spans").checked = config.repair_high_risk_spans !== false;
  if (el("span_translation_max_spans")) el("span_translation_max_spans").value = config.span_translation_max_spans ?? 4;
  if (el("span_translation_max_segments")) el("span_translation_max_segments").value = config.span_translation_max_segments ?? 4;
  if (el("span_translation_max_duration")) el("span_translation_max_duration").value = config.span_translation_max_duration ?? 12.0;
  if (el("span_translation_min_risk_score")) el("span_translation_min_risk_score").value = config.span_translation_min_risk_score ?? 10;
  el("span_repair_max_spans").value = config.span_repair_max_spans ?? 12;
  if (el("semantic_zh_allocation_enabled")) el("semantic_zh_allocation_enabled").checked = config.semantic_zh_allocation_enabled !== false;
  if (el("semantic_zh_allocation_max_spans")) el("semantic_zh_allocation_max_spans").value = config.semantic_zh_allocation_max_spans ?? 16;
  if (el("short_complete_sentence_display_grouping")) el("short_complete_sentence_display_grouping").checked = config.short_complete_sentence_display_grouping !== false;
  el("enable_ai_display_rewrite").checked = Boolean(config.enable_ai_display_rewrite);
  if (el("enable_local_translation_feedback")) el("enable_local_translation_feedback").checked = Boolean(config.enable_local_translation_feedback);
  el("display_rewrite_max_ai_segments").value = config.display_rewrite_max_ai_segments ?? 12;
  if (el("bootstrap_entity_decisions")) {
    el("bootstrap_entity_decisions").value = normalizeBootstrapMode(config.bootstrap_entity_decisions);
  }
  el("download_backend").value = config.download_backend || "auto";
  el("idm_exe_path").value = config.idm_exe_path || "";
  el("idm_output_dir").value = config.idm_output_dir || "";
  el("idm_wait_timeout_seconds").value = config.idm_wait_timeout_seconds ?? 1800;

  const style = config.style || {};
  el("zh_font_name").value = style.zh_font_name || "Maple Mono NF CN";
  el("zh_font_size").value = style.zh_font_size ?? 64;
  setColorField("zh_primary_color", style.zh_primary_color || "#FFF2A6", "#FFF2A6");
  setOpacityField("zh_primary_opacity", style.zh_primary_opacity ?? 100, 100);
  setColorField("zh_outline_color", style.zh_outline_color || "#202020", "#202020");
  setOpacityField("zh_outline_opacity", style.zh_outline_opacity ?? 45, 45);
  setColorField("zh_shadow_color", style.zh_shadow_color || "#000000", "#000000");
  setOpacityField("zh_shadow_opacity", style.zh_shadow_opacity ?? 35, 35);
  el("zh_outline_width").value = style.zh_outline_width ?? 1.8;
  el("zh_shadow_depth").value = style.zh_shadow_depth ?? 0.4;
  el("zh_margin_l").value = style.zh_margin_l ?? 90;
  el("zh_margin_r").value = style.zh_margin_r ?? 90;
  el("zh_margin_v").value = style.zh_margin_v ?? 94;
  el("zh_wrap_trigger_chars").value = style.zh_wrap_trigger_chars ?? 32;
  el("zh_max_chars_per_line").value = style.zh_max_chars_per_line ?? 28;
  el("zh_max_lines").value = style.zh_max_lines ?? 2;
  el("en_font_name").value = style.en_font_name || "Maple Mono NF CN";
  el("en_font_size").value = style.en_font_size ?? 40;
  el("en_margin_l").value = style.en_margin_l ?? 80;
  el("en_margin_r").value = style.en_margin_r ?? 100;
  el("en_margin_v").value = style.en_margin_v ?? 44;
  el("en_max_single_line_chars").value = style.en_max_single_line_chars ?? Math.max(50, (style.en_max_words_per_line ?? 13) * 6);
  el("en_max_split_parts").value = style.en_max_split_parts ?? 3;
  el("min_split_duration").value = style.min_split_duration ?? 0.9;
  el("reference_mode").value = style.reference_mode || "compact";

  updateSubtitleStylePreview();
  setLinkedAudioLabel(config.audio_override_path || "");
  renderWorkflowSummary();
  renderAdvancedStrategySummary();
  renderOpenAiRuntimeStatus();
  renderEntityReviewPanel();
  renderCommandContext();
}

function formatWorkflowDatasetPreview(dataset) {
  if (!dataset || typeof dataset !== "object") return "未加载数据集 profile。";
  const lines = [];
  if (dataset.id) lines.push(`dataset: ${dataset.id}`);
  const files = Array.isArray(dataset.file_names)
    ? dataset.file_names
    : dataset.files && typeof dataset.files === "object"
      ? Object.keys(dataset.files)
      : [];
  if (files.length) lines.push(`files: ${files.join(", ")}`);
  if (typeof dataset.glossary_term_count === "number") lines.push(`glossary terms: ${dataset.glossary_term_count}`);
  if (dataset.glossary_preview) lines.push(String(dataset.glossary_preview).split("\n").slice(0, 6).join("\n"));
  else if (dataset.glossary_text) lines.push(String(dataset.glossary_text).split("\n").slice(0, 6).join("\n"));
  return lines.join("\n\n") || "暂无数据集预览。";
}

function getSelectedWorkflowProfile() {
  const workflowId = el("workflow_profile")?.value || state.config?.workflow_profile || "en_to_zh_default";
  return state.workflowProfiles.find((item) => item.id === workflowId) || null;
}

function currentWorkflowFormValues() {
  return {
    workflow: el("workflow_profile")?.value || state.config?.workflow_profile || "",
    src: el("src_lang")?.value || state.config?.src_lang || "",
    dst: el("dst_lang")?.value || state.config?.dst_lang || "",
    model: el("model")?.value || state.config?.model || "",
    subtitleMode: el("subtitle_mode")?.value || state.config?.subtitle_mode || "",
    sourceReferenceLabel: el("source_reference_label")?.value || state.config?.source_reference_label || "",
    promptProfile: el("prompt_profile")?.value || state.config?.prompt_profile || "",
    datasetProfile: el("dataset_profile")?.value || state.config?.dataset_profile || "",
    localTranslationFeedback: el("enable_local_translation_feedback")?.checked === true || state.config?.enable_local_translation_feedback === true,
    bootstrapEntityDecisions: normalizeBootstrapMode(el("bootstrap_entity_decisions")?.value || state.config?.bootstrap_entity_decisions),
    referenceFont: el("en_font_name")?.value || state.config?.style?.en_font_name || "",
    referenceFontSize: el("en_font_size")?.value || state.config?.style?.en_font_size || "",
    referenceLineLimit: el("en_max_single_line_chars")?.value || state.config?.style?.en_max_single_line_chars || "",
    referenceSplitParts: el("en_max_split_parts")?.value || state.config?.style?.en_max_split_parts || "",
    minSplitDuration: el("min_split_duration")?.value || state.config?.style?.min_split_duration || "",
    referenceMode: el("reference_mode")?.value || state.config?.style?.reference_mode || "",
  };
}

function buildWorkflowWarnings(values, profile) {
  const warnings = [];
  if (!profile && state.workflowProfiles.length) warnings.push("当前工作流 profile 元数据未加载。");
  if (!state.workflowProfiles.length) warnings.push("工作流 profile 列表未加载，请先刷新后再保存配置。");
  const isRussian = values.workflow === "ru_to_zh_default" || values.src === "ru" || values.sourceReferenceLabel === "ru";
  if (isRussian) {
    const styleOk =
      values.referenceFont === "Huiwen-HKHei" &&
      Number(values.referenceFontSize) === 32 &&
      Number(values.referenceLineLimit) === 80 &&
      Number(values.referenceSplitParts) === 4 &&
      Number(values.minSplitDuration) === 1.2 &&
      values.referenceMode === "full_split";
    if (!styleOk) warnings.push("俄文参考层样式应为 Huiwen-HKHei / 32 / 80 / 4 / 1.2 / full_split。");
    if (values.promptProfile && values.promptProfile.startsWith("en_")) warnings.push("俄文工作流当前使用了英文提示词 profile。");
    if (values.datasetProfile && values.datasetProfile.startsWith("en_")) warnings.push("俄文工作流当前使用了英文数据集 profile。");
  }
  return warnings;
}

function renderEffectiveWorkflowSummary(profile) {
  const root = el("effectiveWorkflowSummary");
  if (!root) return;
  const values = currentWorkflowFormValues();
  const rows = [
    ["工作流", `${profile?.label || values.workflow || "未选择"} (${values.workflow || "unknown"})`],
    ["语言方向", `${values.src || "auto"} -> ${values.dst || "zh-Hans"}`],
    ["识别模型", values.model || "未设置"],
    ["字幕模式", values.subtitleMode || "未设置"],
    ["参考层", `${values.referenceFont || "未设置"} / ${values.referenceFontSize || "-"} / ${values.referenceLineLimit || "-"} / ${values.referenceSplitParts || "-"} / ${values.minSplitDuration || "-"} / ${values.referenceMode || "-"}`],
    ["提示词", values.promptProfile || "未设置"],
    ["数据集", values.datasetProfile || "未设置"],
    ["本地反馈", values.localTranslationFeedback ? "开启，注入翻译 Prompt" : "关闭，仅保留数据采集"],
    ["实体决策", values.bootstrapEntityDecisions || "high_confidence_only"],
  ];
  root.innerHTML = rows
    .map(([label, value]) => `<div class="workflow-effective-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const warningNode = el("workflowWarningSummary");
  if (!warningNode) return;
  const warnings = buildWorkflowWarnings(values, profile);
  warningNode.innerHTML = warnings.map((warning) => `<span class="workflow-warning-chip">${escapeHtml(warning)}</span>`).join("");
}

function applyWorkflowProfileSelection(profileId) {
  const profile = state.workflowProfiles.find((item) => item.id === profileId);
  if (!profile) return;
  if (el("workflow_profile")) el("workflow_profile").value = profile.id;
  if (el("src_lang")) el("src_lang").value = profile.src_lang || "";
  if (el("dst_lang")) el("dst_lang").value = profile.dst_lang || "";
  if (el("model")) el("model").value = profile.model || "";
  if (el("prompt_profile")) el("prompt_profile").value = profile.prompt_profile || "";
  if (el("dataset_profile")) el("dataset_profile").value = profile.dataset_profile || "";
  if (el("subtitle_mode")) el("subtitle_mode").value = profile.subtitle_mode || "bilingual_source_reference";
  if (el("source_reference_label")) el("source_reference_label").value = profile.source_reference_label || profile.src_lang || "";

  const configDefaults = profile.config && typeof profile.config === "object" ? profile.config : {};
  const styleDefaults = profile.style && typeof profile.style === "object" ? profile.style : {};
  Object.entries(configDefaults).forEach(([key, value]) => {
    const node = el(key);
    if (!node) return;
    if (node.type === "checkbox") {
      node.checked = Boolean(value);
    } else {
      node.value = value ?? "";
    }
  });
  Object.entries(styleDefaults).forEach(([key, value]) => {
    const node = el(key);
    if (!node) return;
    node.value = value ?? "";
  });

  if (profile.prompt_preview && el("translation_prompt")) {
    el("translation_prompt").value = profile.prompt_preview;
  }
  state.activePromptProfile = profile.prompt_preview || "";
  state.activeDatasetProfile = profile.dataset_summary || null;
  updateSubtitleStylePreview();
  markConfigDirty();
}

function renderWorkflowProfiles() {
  const select = el("workflow_profile");
  if (!select) return;
  const currentValue = select.value || state.config?.workflow_profile || DEFAULT_UI_CONFIG.workflow_profile;
  select.innerHTML = "";
  (state.workflowProfiles || []).forEach((profile) => {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = profile.label || profile.id;
    select.appendChild(option);
  });
  select.value = currentValue;
}

function renderWorkflowSummary() {
  const profile = getSelectedWorkflowProfile();
  renderEffectiveWorkflowSummary(profile);
  const promptNode = el("workflowPromptPreview");
  const datasetNode = el("workflowDatasetPreview");
  const descriptionNode = el("workflowProfileDescription");
  const pairNode = el("workflow_pair_preview");
  const currentPromptProfile = el("prompt_profile")?.value || state.config?.prompt_profile || "";
  const currentDatasetProfile = el("dataset_profile")?.value || state.config?.dataset_profile || "";
  const profileOwnsPrompt = profile && profile.prompt_profile === currentPromptProfile;
  const profileOwnsDataset = profile && profile.dataset_profile === currentDatasetProfile;
  if (descriptionNode) {
    descriptionNode.textContent = profile?.description || "请选择一个工作流 profile，以加载语言方向、提示词、数据集和参考层默认值。";
  }
  if (promptNode) {
    const text = profileOwnsPrompt
      ? (profile?.prompt_preview || state.activePromptProfile || el("translation_prompt")?.value || "")
      : (el("translation_prompt")?.value || "");
    promptNode.textContent = text ? text.slice(0, 900) : "未加载提示词。";
  }
  if (datasetNode) {
    const dataset = profileOwnsDataset ? (profile?.dataset_summary || state.activeDatasetProfile) : state.activeDatasetProfile;
    datasetNode.textContent = formatWorkflowDatasetPreview(dataset);
  }
  if (pairNode) {
    const src = el("src_lang")?.value || state.config?.src_lang || "";
    const dst = el("dst_lang")?.value || state.config?.dst_lang || "";
    const mode = el("subtitle_mode")?.value || state.config?.subtitle_mode || "";
    pairNode.value = `${src} -> ${dst} / ${mode}`;
  }
  renderCommandContext();
  renderLocalFeedbackSummary(state.localFeedbackSummary);
}

function renderAdvancedStrategySummary() {
  const root = el("advancedStrategySummary");
  if (!root) return;
  const config = normalizeUiConfig(state.config || readFormConfig());
  const rows = [
    ["缓存与重跑", `复用分段${yesNo(config.load_existing_segments)} / 强制重翻${yesNo(config.force_retranslate_existing_segments)} / 只出 ASS${yesNo(config.skip_burn)}`],
    ["难句修复", `AI 修复${yesNo(config.repair_high_risk_spans)} / 预翻译 ${config.span_translation_max_spans ?? 0} spans / 修复 ${config.span_repair_max_spans ?? 0} spans`],
    ["语义分配", `中文语义分配${yesNo(config.semantic_zh_allocation_enabled !== false)} / ${config.semantic_zh_allocation_max_spans ?? 0} spans / 短句合屏${yesNo(config.short_complete_sentence_display_grouping !== false)}`],
    ["实体与重写", `AI 风格重写${yesNo(config.enable_ai_display_rewrite)} / 最多 ${config.display_rewrite_max_ai_segments ?? 0} 段 / Entity ${normalizeBootstrapMode(config.bootstrap_entity_decisions)}`],
  ];
  root.innerHTML = rows
    .map(([label, value]) => `<div class="workflow-effective-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
}

function openaiSourceLabel(source) {
  const labels = {
    process_env: "进程环境变量",
    user_env: "User 环境变量",
    machine_env: "Machine 环境变量",
    ui_config: "网页配置",
    missing: "未检测到",
  };
  return labels[source] || source || "未知来源";
}

function renderOpenAiRuntimeStatus() {
  const card = el("openaiRuntimeCard");
  if (!card) return;
  const runtime = state.openaiRuntime || {};
  const apiKey = runtime.api_key || {};
  const baseUrl = runtime.base_url || {};
  const configuredBaseUrl = el("openai_base_url")?.value?.trim() || "";
  const displayBaseUrl = configuredBaseUrl
    ? { available: true, source: "ui_config", value: configuredBaseUrl, env_name: "openai_base_url" }
    : baseUrl;
  const apiKeyText = apiKey.available
    ? `已检测到 · ${openaiSourceLabel(apiKey.source)} · ${apiKey.masked || "已隐藏"}`
    : "未检测到";
  const baseUrlText = displayBaseUrl.available
    ? `${displayBaseUrl.source === "ui_config" ? "使用网页配置" : "已检测到"} · ${openaiSourceLabel(displayBaseUrl.source)} · ${displayBaseUrl.value || ""}`
    : "未检测到，使用 OpenAI 官方默认地址";
  const warning = apiKey.available
    ? ""
    : `<div class="openai-runtime-warning">高风险修复、AI 显示重写、OpenAI 翻译步骤需要 OPENAI_API_KEY。</div>`;
  card.innerHTML = `
    <div class="openai-runtime-head">
      <div>
        <strong>OpenAI 运行环境</strong>
        <span>网页只显示状态；API Key 不会以明文返回前端。</span>
      </div>
      <button id="refreshOpenAiRuntimeBtn" type="button" class="mini-btn icon-btn">${buttonSvg("refresh")}<span class="button-label">重新检测</span></button>
    </div>
    <div class="openai-runtime-row ${apiKey.available ? "ok" : "missing"}">
      <span>API Key</span>
      <strong>${escapeHtml(apiKeyText)}</strong>
    </div>
    <div class="openai-runtime-row ${displayBaseUrl.available ? "ok" : "muted"}">
      <span>Base URL</span>
      <strong>${escapeHtml(baseUrlText)}</strong>
    </div>
    ${warning}
  `;
  el("refreshOpenAiRuntimeBtn")?.addEventListener("click", refreshOpenAiRuntimeStatus);
}

function fillFormIfClean(config) {
  if (state.formDirty) return;
  fillForm(config);
}

function renderMediaAlert() {
  const card = el("mediaAlertCard");
  const media = state.selectedMediaInfo;
  if (!state.selectedVideo || !media) {
    card.classList.add("hidden");
    card.innerHTML = "";
    renderCommandContext();
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
    renderCommandContext();
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
  renderCommandContext();
}

function commandWorkflowText() {
  const config = normalizeUiConfig(state.config || readFormConfig());
  return `${config.src_lang || "auto"} -> ${config.dst_lang || "zh-Hans"} / ${config.subtitle_mode || "bilingual_source_reference"} / ${config.dataset_profile || "default"}`;
}

function renderCommandContext() {
  const configNode = el("commandConfigState");
  if (configNode) {
    const feedback = state.config?.enable_local_translation_feedback ? "反馈开" : "反馈关";
    configNode.textContent = `${commandWorkflowText()} / ${feedback}`;
  }

  const metaNode = el("selectedVideoMeta");
  if (!metaNode || !state.selectedVideo) return;
  const media = state.selectedMediaInfo;
  const audioOverride = state.config?.audio_override_path || el("audio_override_path")?.value || "";
  if (!media) {
    metaNode.textContent = `输入路径：${state.selectedVideo.path}`;
    return;
  }
  const details = [
    `时长 ${seconds(media.duration_seconds || 0)}`,
    `音频 ${media.has_audio ? "有" : "无"}`,
    `MP3 ${audioOverride ? "已附加" : "未附加"}`,
  ];
  metaNode.textContent = `${details.join(" / ")} · ${state.selectedVideo.path}`;
}

function renderLocalFeedbackSummary(payload) {
  const root = el("localFeedbackSummaryCard");
  if (!root) return;
  const config = normalizeUiConfig(state.config || DEFAULT_UI_CONFIG);
  if (!payload) {
    root.innerHTML = `
      <div class="local-feedback-head">
        <div>
          <h4>本地翻译反馈</h4>
          <p>正在读取本地学习摘要...</p>
        </div>
        <span class="entity-chip muted">${yesNo(config.enable_local_translation_feedback)}</span>
      </div>
    `;
    return;
  }

  const counts = payload.counts || {};
  const evalInfo = payload.eval || {};
  const metrics = evalInfo.metrics || {};
  const guidelines = Array.isArray(payload.guidelines) ? payload.guidelines.slice(0, 5) : [];
  const available = payload.available || {};
  const statusChip = config.enable_local_translation_feedback ? "已接入 Prompt" : "未注入 Prompt";
  const selectedProjectPath = currentFeedbackProjectPath() || "";
  const selectedAssFile = /\.ass$/i.test(state.selectedFilePath || "");
  const selectedProject =
    (state.projects || []).find((project) => project.path === selectedProjectPath) ||
    (state.selectedProject?.path === selectedProjectPath ? state.selectedProject : null);
  const selectedProjectName = selectedProject?.name || (selectedProjectPath ? selectedProjectPath.split(/[\\/]/).filter(Boolean).pop() : "");
  const projectSourceLabel = currentFeedbackProjectSourceLabel();
  const rawAction = state.localFeedbackAction || {};
  const action = rawAction.projectPath === selectedProjectPath ? rawAction : {};
  const actionBusy = action.status === "running";
  const actionText =
    action.status === "success"
      ? action.message
      : action.status === "error"
        ? action.message
        : selectedProjectName
          ? `学习目标：${projectSourceLabel} -> ${selectedProjectName}`
          : "请先在项目产物中选择对应 ASS 文件";
  const actionClass = action.status === "error" ? " error" : action.status === "success" ? " ok" : "";
  root.innerHTML = `
    <div class="local-feedback-head">
      <div>
        <h4>本地翻译反馈</h4>
        <p>${escapeHtml(statusChip)} · ${escapeHtml(payload.dataset_dir || "datasets/local_feedback")}</p>
      </div>
      <span class="entity-chip ${config.enable_local_translation_feedback ? "" : "muted"}">反馈${yesNo(config.enable_local_translation_feedback)}</span>
    </div>
    <div class="feedback-summary-grid">
      <div class="entity-metric"><span>翻译编辑样本</span><strong>${escapeHtml(counts.translation_edit_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>风格学习样本</span><strong>${escapeHtml(counts.style_learning_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>Eval Gold</span><strong>${escapeHtml(counts.style_gold_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>最新 Eval 样本</span><strong>${escapeHtml(evalInfo.sample_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>不安全样本率</span><strong>${escapeHtml(formatPercent(metrics.unsafe_sample_rate ?? 0))}</strong></div>
      <div class="entity-metric"><span>语义/风格信号</span><strong>${escapeHtml(formatPercent(metrics.semantic_or_style_signal_rate ?? 0))}</strong></div>
    </div>
    <div class="local-feedback-guidelines">
      <strong>已学习规则预览</strong>
      ${
        guidelines.length
          ? `<ul>${guidelines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
          : `<p>${available.learned_style_guidelines ? "暂无可预览规则" : "还没有 learned_style_guidelines.md，先采集并学习 ASS 反馈。"}</p>`
      }
    </div>
  `;
  root.insertAdjacentHTML(
    "beforeend",
    `
    <div class="local-feedback-actions">
      <button id="collectCurrentAssFeedbackBtn" class="mini-btn" type="button" ${!selectedProjectPath || !selectedAssFile || actionBusy ? "disabled" : ""}>学习本次 ASS</button>
      <button id="collectCurrentSpanFeedbackBtn" class="mini-btn" type="button" ${!selectedProjectPath || !selectedAssFile || actionBusy ? "disabled" : ""}>学习本次 Span</button>
      <span class="local-feedback-action-status${actionClass}">${escapeHtml(actionBusy ? "正在采集学习样本..." : actionText || "")}</span>
    </div>
    <p class="local-feedback-note">学习来源只取最终人工 ASS；05/05a 只作为机器基线用于差异对齐，不作为学习目标。</p>
  `,
  );
  wireLocalFeedbackActionButtons();
  const spanEvalInfo = payload.span_eval || {};
  const spanMetrics = spanEvalInfo.metrics || {};
  const feedbackGrid = root.querySelector(".feedback-summary-grid");
  if (feedbackGrid) {
    feedbackGrid.insertAdjacentHTML(
      "beforeend",
      `
      <div class="entity-metric"><span>Span samples</span><strong>${escapeHtml(counts.span_translation_example_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>Span learning</span><strong>${escapeHtml(counts.span_style_learning_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>Span eval</span><strong>${escapeHtml(counts.span_eval_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>Span reallocation</span><strong>${escapeHtml(formatPercent(spanMetrics.semantic_reallocation_rate ?? 0))}</strong></div>
      <div class="entity-metric"><span>Span fragments</span><strong>${escapeHtml(formatPercent(spanMetrics.fragment_completion_rate ?? 0))}</strong></div>
      <div class="entity-metric"><span>Span unsafe</span><strong>${escapeHtml(formatPercent(spanMetrics.unsafe_sample_rate ?? 0))}</strong></div>
    `,
    );
  }
  const spanGuidelines = Array.isArray(payload.span_guidelines) ? payload.span_guidelines.slice(0, 4) : [];
  const availableSpanGuidelines = payload.available || {};
  root.insertAdjacentHTML(
    "beforeend",
    `
    <div class="local-feedback-guidelines">
      <strong>Span learned rules preview</strong>
      ${
        spanGuidelines.length
          ? `<ul>${spanGuidelines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
          : `<p>${availableSpanGuidelines.learned_span_guidelines ? "No span rules to preview yet." : "No learned_span_guidelines.md yet; collect span feedback first."}</p>`
      }
    </div>
  `,
  );
}

function currentFeedbackProjectPath() {
  return state.selectedFileProjectPath || state.selectedProject?.path || null;
}

function currentFeedbackProjectSourceLabel() {
  if (state.selectedFileProjectPath) return "当前 ASS 文件";
  if (state.selectedProject?.path) return "当前产物项目";
  return "未选择";
}

function localFeedbackResultMessage(kind, payload) {
  const label = kind === "span" ? "Span" : "ASS";
  const added = Number(payload?.added || 0);
  const skipped = Number(payload?.skipped_existing || 0);
  if (kind === "span") {
    const collected = Number(payload?.added_span_record_count || 0);
    const candidates = Number(payload?.candidate_span_count || 0);
    return `${label} 学习样本已采集：新增 ${added} 条，生成 ${collected} 条，候选 span ${candidates} 个，跳过重复 ${skipped} 条`;
  }
  const changed = Number(payload?.changed_pair_count || 0);
  return `${label} 学习样本已采集：新增 ${added} 条，人工修改 ${changed} 条，跳过重复 ${skipped} 条`;
}

async function collectLocalFeedback(kind) {
  const projectPath = currentFeedbackProjectPath();
  if (!projectPath) {
    showToast("请先在项目产物中选择对应 ASS 文件", "warn");
    return;
  }
  if (!/\.ass$/i.test(state.selectedFilePath || "")) {
    showToast("请先选择要学习的 ASS 产物文件", "warn");
    return;
  }
  const endpoint = kind === "span" ? "/api/collect-span-feedback" : "/api/collect-style-feedback";
  state.localFeedbackAction = { status: "running", kind, projectPath };
  renderLocalFeedbackSummary(state.localFeedbackSummary);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || `${kind} feedback collection failed`);
    const message = `${localFeedbackResultMessage(kind, payload)}；05/05a 仅作基线`;
    state.localFeedbackAction = { status: "success", kind, projectPath, message };
    showToast(message);
    await refreshLocalFeedbackSummary();
    refreshLearningQualitySummary();
    if (state.feedbackReview.kind === kind || (kind === "ass" && state.feedbackReview.kind === "style")) {
      refreshFeedbackReview();
    }
  } catch (error) {
    const label = kind === "span" ? "Span" : "ASS";
    const message = `${label} 学习采集失败：${error.message || error}`;
    state.localFeedbackAction = { status: "error", kind, projectPath, message };
    renderLocalFeedbackSummary(state.localFeedbackSummary);
    showToast(message, "error");
  }
}

function wireLocalFeedbackActionButtons() {
  const assButton = el("collectCurrentAssFeedbackBtn");
  const spanButton = el("collectCurrentSpanFeedbackBtn");
  if (assButton) {
    setButtonContent(assButton, "spark");
    assButton.title = "从本项目最终 ASS 采集翻译编辑样本；05 只作机器基线。";
    assButton.addEventListener("click", () => collectLocalFeedback("ass"));
  }
  if (spanButton) {
    setButtonContent(spanButton, "spark");
    spanButton.title = "从本项目最终 ASS 采集 span 预翻译样本；05/05a 只作机器基线。";
    spanButton.addEventListener("click", () => collectLocalFeedback("span"));
  }
}

async function refreshLocalFeedbackSummary() {
  try {
    const response = await fetch("/api/local-feedback-summary");
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) throw new Error(payload?.error || "local feedback summary failed");
    state.localFeedbackSummary = payload;
  } catch {
    state.localFeedbackSummary = {
      ok: false,
      counts: {},
      eval: { metrics: {} },
      span_eval: { metrics: {} },
      guidelines: [],
      span_guidelines: [],
      available: {},
    };
  }
  renderLocalFeedbackSummary(state.localFeedbackSummary);
}

function feedbackPromptField(kind = state.feedbackReview.kind) {
  return kind === "span" ? "use_for_span_prompt" : "use_for_style_prompt";
}

function feedbackSuggestedActionLabel(action) {
  const labels = {
    use_for_prompt: "推荐 Prompt",
    use_for_eval: "推荐 Eval",
    accept_only: "建议接受",
    review_only: "人工复核",
  };
  return labels[action] || "人工复核";
}

function feedbackSuggestedActionClass(action) {
  if (action === "use_for_prompt" || action === "use_for_eval") return "ok";
  if (action === "accept_only") return "warn";
  return "muted";
}

function feedbackBulkActionLabel(action) {
  const labels = {
    accept: "批量接受",
    use_for_prompt: "批量用于 Prompt",
    use_for_eval: "批量用于 Eval",
    clear_usage: "清除用途",
    return_pending: "退回待审",
  };
  return labels[action] || "批量处理";
}

function selectedFeedbackRecordIds() {
  const visibleIds = new Set((state.feedbackReview.records || []).map((record) => record.record_id));
  return (state.feedbackReview.selectedRecordIds || []).filter((recordId) => visibleIds.has(recordId));
}

function setFeedbackSelection(recordIds) {
  state.feedbackReview.selectedRecordIds = Array.from(new Set(recordIds.filter(Boolean)));
  renderFeedbackReviewPanel();
}

function feedbackSuggestionCounts(records) {
  return (records || []).reduce(
    (acc, record) => {
      const action = record.suggested_action || "review_only";
      acc[action] = (acc[action] || 0) + 1;
      return acc;
    },
    { use_for_prompt: 0, use_for_eval: 0, accept_only: 0, review_only: 0 },
  );
}

function renderJsonBlock(payload) {
  return `<pre class="feedback-json-preview">${escapeHtml(JSON.stringify(payload || {}, null, 2))}</pre>`;
}

function renderFeedbackDetailDrawer() {
  const detailState = state.feedbackReview.detail;
  if (!state.feedbackReview.detailRecordId && !detailState) return "";
  if (state.feedbackReview.detailLoading) {
    return `
      <aside class="feedback-detail-drawer">
        <div class="entity-section-head">
          <h5>样本详情</h5>
          <button class="mini-btn" type="button" data-feedback-detail-close>关闭</button>
        </div>
        <div class="entity-loading">正在读取样本详情...</div>
      </aside>
    `;
  }
  if (!detailState || detailState.ok === false) {
    return `
      <aside class="feedback-detail-drawer">
        <div class="entity-section-head">
          <h5>样本详情</h5>
          <button class="mini-btn" type="button" data-feedback-detail-close>关闭</button>
        </div>
        <div class="entity-alert">详情读取失败：${escapeHtml(detailState?.error || "unknown error")}</div>
      </aside>
    `;
  }
  const detail = detailState.detail || {};
  const preview = detailState.preview || {};
  const isSpan = detailState.kind === "span";
  return `
    <aside class="feedback-detail-drawer">
      <div class="entity-section-head">
        <h5>${isSpan ? "Span 样本详情" : "ASS 样本详情"}</h5>
        <button class="mini-btn" type="button" data-feedback-detail-close>关闭</button>
      </div>
      <div class="feedback-detail-meta">
        <span class="entity-chip ${preview.accepted ? "" : "muted"}">${preview.accepted ? "已接受" : "待审核"}</span>
        <span class="entity-chip ${preview.use_for_prompt ? "ok" : "muted"}">Prompt ${preview.use_for_prompt ? "是" : "否"}</span>
        <span class="entity-chip ${preview.use_for_eval ? "ok" : "muted"}">Eval ${preview.use_for_eval ? "是" : "否"}</span>
        <span class="entity-chip ${detail.learning_risk === "high" ? "danger" : detail.learning_risk === "medium" ? "warn" : "ok"}">风险 ${escapeHtml(detail.learning_risk || "low")}</span>
        <span class="entity-chip ${feedbackSuggestedActionClass(detail.suggestion?.suggested_action)}">${escapeHtml(feedbackSuggestedActionLabel(detail.suggestion?.suggested_action))}</span>
      </div>
      <div class="learning-ratio-list">
        <div><span>项目</span><strong>${escapeHtml(detail.project_id || "")}</strong></div>
        <div><span>创建时间</span><strong>${escapeHtml(detail.created_at || "")}</strong></div>
        <div><span>推荐用途</span><strong>${escapeHtml(detail.learning_recommendation || "")}</strong></div>
        ${isSpan ? `<div><span>Span ID</span><strong>${escapeHtml(detail.span_id || "")}</strong></div>` : `<div><span>Segment ID</span><strong>${escapeHtml(detail.segment_id ?? "")}</strong></div>`}
      </div>
      <div class="project-badges">${(detail.tags || []).map((tag) => `<span class="project-badge">${escapeHtml(tag)}</span>`).join("") || `<span class="project-badge muted">无标签</span>`}</div>
      ${
        isSpan
          ? `
            <div class="feedback-detail-section"><span>Span 原文</span><p>${escapeHtml(detail.source_joined || "")}</p></div>
            <div class="feedback-comparison">
              <div><span>前文</span>${renderJsonBlock(detail.context_before || [])}</div>
              <div><span>机器基线</span>${renderJsonBlock(detail.machine_target_by_id || {})}</div>
              <div><span>人工 ASS</span>${renderJsonBlock(detail.manual_target_by_id || {})}</div>
            </div>
            <div class="feedback-detail-section"><span>Prompt 示例预览</span>${renderJsonBlock(detail.prompt_example_preview || {})}</div>
          `
          : `
            <div class="feedback-comparison">
              <div><span>原文</span><p>${escapeHtml(detail.source_text || "")}</p></div>
              <div><span>机器基线</span><p>${escapeHtml(detail.machine_target_text || "")}</p></div>
              <div><span>人工 ASS</span><p>${escapeHtml(detail.manual_target_text || "")}</p></div>
            </div>
            <div class="feedback-detail-section"><span>操作摘要</span>${renderJsonBlock(detail.operation_summary || {})}</div>
          `
      }
      <div class="feedback-detail-section"><span>分类理由</span>${renderJsonBlock(detail.classification_reasons || [])}</div>
      <div class="feedback-detail-actions">
        <button class="mini-btn" type="button" data-feedback-action="accept" data-feedback-record-id="${escapeHtml(detailState.record_id)}">接受</button>
        <button class="mini-btn" type="button" data-feedback-action="prompt" data-feedback-record-id="${escapeHtml(detailState.record_id)}">用于 Prompt</button>
        <button class="mini-btn" type="button" data-feedback-action="eval" data-feedback-record-id="${escapeHtml(detailState.record_id)}">用于 Eval</button>
        <button class="mini-btn" type="button" data-feedback-action="clear" data-feedback-record-id="${escapeHtml(detailState.record_id)}">取消使用</button>
        <button class="mini-btn" type="button" data-feedback-action="reject" data-feedback-record-id="${escapeHtml(detailState.record_id)}">退回待审</button>
      </div>
    </aside>
  `;
}

function syncFeedbackReviewControls() {
  const kindNode = el("feedbackReviewKind");
  const statusNode = el("feedbackReviewStatus");
  if (kindNode) kindNode.value = state.feedbackReview.kind;
  if (statusNode) statusNode.value = state.feedbackReview.status;
}

function renderFeedbackTags(record) {
  const tags = [...(record.edit_tags || []), ...(record.feedback_types || [])].filter(Boolean);
  if (!tags.length) return `<span class="project-badge muted">无标签</span>`;
  return tags.map((tag) => `<span class="project-badge">${escapeHtml(tag)}</span>`).join("");
}

function renderFeedbackReviewPanel() {
  const root = el("feedbackReviewPanel");
  if (!root) return;
  syncFeedbackReviewControls();
  const review = state.feedbackReview;
  if (review.loading) {
    root.innerHTML = `
      <div class="entity-panel">
        <div class="entity-panel-head">
          <div>
            <h4>正在读取审核样本</h4>
            <p>从本地 JSONL 数据集中读取，不会触发翻译请求。</p>
          </div>
        </div>
      </div>
    `;
    return;
  }
  const records = Array.isArray(review.records) ? review.records : [];
  const selectedIds = selectedFeedbackRecordIds();
  const selectedSet = new Set(selectedIds);
  const suggestionCounts = feedbackSuggestionCounts(records);
  const lowRiskIds = records
    .filter((record) => {
      const tags = [...(record.edit_tags || []), ...(record.feedback_types || [])];
      return record.learning_risk !== "high" && !tags.includes("bad_alignment") && !tags.includes("bad_example");
    })
    .map((record) => record.record_id);
  if (!records.length) {
    root.innerHTML = `
      <div class="entity-panel">
        <div class="entity-panel-head">
          <div>
            <h4>暂无可审核样本</h4>
            <p>${escapeHtml(review.message || "当前筛选条件下没有记录。可以先在项目产物里选择 ASS，再点击“学习本次 ASS”或“学习本次 Span”。")}</p>
          </div>
        </div>
        <p class="local-feedback-note">说明：05/05a 只作为机器基线参与差异对齐，不会作为人工学习目标写入。</p>
      </div>
    `;
    return;
  }
  root.innerHTML = `
    <div class="feedback-review-explain">
      <strong>审核规则</strong>
      <p>用于 Prompt 的样本会被后续翻译检索注入；Eval 样本只用于离线评估，二者互斥。批量操作只修改本地 JSONL 元数据，不会启动字幕翻译，也不会增加模型请求量。</p>
      ${review.kind === "span" ? `<p>05/05a 仅作为机器基线；high-risk、bad_alignment 或 bad-example 不会批量进入 Prompt/Eval。</p>` : ""}
      ${review.message ? `<p>${escapeHtml(review.message)}</p>` : ""}
    </div>
    <div class="feedback-bulk-panel">
      <div class="feedback-bulk-summary">
        <span class="entity-chip ok">推荐 Prompt ${escapeHtml(suggestionCounts.use_for_prompt || 0)}</span>
        <span class="entity-chip ok">推荐 Eval ${escapeHtml(suggestionCounts.use_for_eval || 0)}</span>
        <span class="entity-chip warn">建议接受 ${escapeHtml(suggestionCounts.accept_only || 0)}</span>
        <span class="entity-chip muted">需人工复核 ${escapeHtml(suggestionCounts.review_only || 0)}</span>
        <span class="entity-chip">已选择 ${escapeHtml(selectedIds.length)}</span>
      </div>
      <div class="feedback-record-actions">
        <button class="mini-btn" type="button" data-feedback-select="page" ${review.bulkBusy ? "disabled" : ""}>选择本页</button>
        <button class="mini-btn" type="button" data-feedback-select="low-risk" ${review.bulkBusy ? "disabled" : ""}>仅选低风险</button>
        <button class="mini-btn" type="button" data-feedback-select="clear" ${review.bulkBusy ? "disabled" : ""}>清空选择</button>
        <button class="mini-btn" type="button" data-feedback-bulk-action="accept" ${review.bulkBusy || !selectedIds.length ? "disabled" : ""}>批量接受</button>
        <button class="mini-btn" type="button" data-feedback-bulk-action="use_for_prompt" ${review.bulkBusy || !selectedIds.length ? "disabled" : ""}>批量用于 Prompt</button>
        <button class="mini-btn" type="button" data-feedback-bulk-action="use_for_eval" ${review.bulkBusy || !selectedIds.length ? "disabled" : ""}>批量用于 Eval</button>
        <button class="mini-btn" type="button" data-feedback-bulk-action="clear_usage" ${review.bulkBusy || !selectedIds.length ? "disabled" : ""}>清除用途</button>
        <button class="mini-btn" type="button" data-feedback-bulk-action="return_pending" ${review.bulkBusy || !selectedIds.length ? "disabled" : ""}>退回待审</button>
        <button class="mini-btn" type="button" data-feedback-bulk-suggested="use_for_prompt" ${review.bulkBusy || !suggestionCounts.use_for_prompt ? "disabled" : ""}>按推荐加入 Prompt</button>
        <button class="mini-btn" type="button" data-feedback-bulk-suggested="use_for_eval" ${review.bulkBusy || !suggestionCounts.use_for_eval ? "disabled" : ""}>按推荐加入 Eval</button>
      </div>
    </div>
    <div class="feedback-record-list">
      ${records
        .map((record) => {
          const isBusy = review.selectedRecordId === record.record_id;
          const title =
            review.kind === "span"
              ? `Span ${record.span_id || record.index || ""} · ${Array.isArray(record.segment_ids) ? record.segment_ids.join(", ") : ""}`
              : `分段 ${record.segment_id ?? record.index ?? ""}`;
          const riskClass = record.learning_risk === "high" ? "danger" : record.learning_risk === "medium" ? "warn" : "ok";
          const suggestionClass = feedbackSuggestedActionClass(record.suggested_action);
          return `
            <article class="feedback-record">
              <div class="feedback-record-head">
                <label class="feedback-record-select">
                  <input type="checkbox" data-feedback-select-record="${escapeHtml(record.record_id)}" ${selectedSet.has(record.record_id) ? "checked" : ""} ${review.bulkBusy ? "disabled" : ""}>
                  <span>
                    <h4>${escapeHtml(title)}</h4>
                    <p>${escapeHtml(record.project_id || "unknown project")}</p>
                  </span>
                </label>
                <div>
                  <span class="entity-chip ${suggestionClass}">${escapeHtml(feedbackSuggestedActionLabel(record.suggested_action))}</span>
                  <p>${escapeHtml(record.suggestion_reason || record.learning_recommendation || "人工复核")}</p>
                </div>
                <div class="feedback-status-row">
                  <span class="entity-chip ${record.accepted ? "" : "muted"}">${record.accepted ? "已接受" : "待审核"}</span>
                  <span class="entity-chip ${record.use_for_prompt ? "" : "muted"}">Prompt ${record.use_for_prompt ? "是" : "否"}</span>
                  <span class="entity-chip ${record.use_for_eval ? "" : "muted"}">Eval ${record.use_for_eval ? "是" : "否"}</span>
                  <span class="entity-chip ${riskClass}">风险 ${escapeHtml(record.learning_risk || "low")}</span>
                </div>
              </div>
              <div class="feedback-comparison">
                <div><span>原文</span><p>${escapeHtml(record.source || "")}</p></div>
                <div><span>机器基线</span><p>${escapeHtml(record.machine || "")}</p></div>
                <div><span>人工 ASS</span><p>${escapeHtml(record.manual || "")}</p></div>
              </div>
              <div class="project-badges">${renderFeedbackTags(record)}</div>
              <p class="local-feedback-note">建议：${escapeHtml(record.learning_recommendation || "人工复核")} · ${escapeHtml(record.created_at || "")}</p>
              <div class="feedback-record-actions">
                <button class="mini-btn" type="button" data-feedback-detail-id="${escapeHtml(record.record_id)}">查看详情</button>
                <button class="mini-btn" type="button" data-feedback-action="accept" data-feedback-record-id="${escapeHtml(record.record_id)}" ${isBusy ? "disabled" : ""}>接受</button>
                <button class="mini-btn" type="button" data-feedback-action="prompt" data-feedback-record-id="${escapeHtml(record.record_id)}" ${isBusy ? "disabled" : ""}>用于 Prompt</button>
                <button class="mini-btn" type="button" data-feedback-action="eval" data-feedback-record-id="${escapeHtml(record.record_id)}" ${isBusy ? "disabled" : ""}>用于 Eval</button>
                <button class="mini-btn" type="button" data-feedback-action="clear" data-feedback-record-id="${escapeHtml(record.record_id)}" ${isBusy ? "disabled" : ""}>取消使用</button>
                <button class="mini-btn" type="button" data-feedback-action="reject" data-feedback-record-id="${escapeHtml(record.record_id)}" ${isBusy ? "disabled" : ""}>退回待审</button>
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
    ${renderFeedbackDetailDrawer()}
  `;
  root.querySelectorAll("[data-feedback-select]").forEach((button) => {
    button.addEventListener("click", () => {
      const mode = button.getAttribute("data-feedback-select") || "";
      if (mode === "page") setFeedbackSelection(records.map((record) => record.record_id));
      if (mode === "low-risk") setFeedbackSelection(lowRiskIds);
      if (mode === "clear") setFeedbackSelection([]);
    });
  });
  root.querySelectorAll("[data-feedback-select-record]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const recordId = checkbox.getAttribute("data-feedback-select-record") || "";
      const next = new Set(selectedFeedbackRecordIds());
      if (checkbox.checked) next.add(recordId);
      else next.delete(recordId);
      setFeedbackSelection([...next]);
    });
  });
  root.querySelectorAll("[data-feedback-bulk-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.getAttribute("data-feedback-bulk-action") || "";
      updateFeedbackReviewBulk(action, { record_ids: selectedFeedbackRecordIds() });
    });
  });
  root.querySelectorAll("[data-feedback-bulk-suggested]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestedAction = button.getAttribute("data-feedback-bulk-suggested") || "";
      updateFeedbackReviewBulk(suggestedAction, {
        filter: {
          status: state.feedbackReview.status,
          suggested_actions: [suggestedAction],
          exclude_tags: ["bad_alignment", "bad_example"],
        },
      });
    });
  });
  root.querySelectorAll("[data-feedback-detail-id]").forEach((button) => {
    button.addEventListener("click", () => loadFeedbackRecordDetail(button.getAttribute("data-feedback-detail-id") || ""));
  });
  root.querySelectorAll("[data-feedback-detail-close]").forEach((button) => {
    button.addEventListener("click", () => {
      state.feedbackReview.detailRecordId = "";
      state.feedbackReview.detail = null;
      state.feedbackReview.detailLoading = false;
      renderFeedbackReviewPanel();
    });
  });
  root.querySelectorAll("[data-feedback-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const recordId = button.getAttribute("data-feedback-record-id") || "";
      const action = button.getAttribute("data-feedback-action") || "";
      const promptField = feedbackPromptField();
      const updatesByAction = {
        accept: { accepted: true },
        prompt: { accepted: true, [promptField]: true, use_for_eval: false },
        eval: { accepted: true, [promptField]: false, use_for_eval: true },
        clear: { [promptField]: false, use_for_eval: false },
        reject: { accepted: false, [promptField]: false, use_for_eval: false },
      };
      updateFeedbackReviewRecord(recordId, updatesByAction[action] || {});
    });
  });
}

async function refreshFeedbackReview() {
  state.feedbackReview.loading = true;
  state.feedbackReview.message = "";
  renderFeedbackReviewPanel();
  try {
    const params = new URLSearchParams({
      kind: state.feedbackReview.kind,
      status: state.feedbackReview.status,
      limit: "100",
    });
    const response = await fetch(`/api/local-feedback-records?${params.toString()}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "读取审核样本失败");
    state.feedbackReview.records = Array.isArray(payload.records) ? payload.records : [];
    state.feedbackReview.selectedRecordIds = selectedFeedbackRecordIds();
    state.feedbackReview.message = `${payload.source_label || "学习样本"}：显示 ${payload.records?.length || 0} / ${payload.filtered_count || 0} 条，数据集总计 ${payload.total || 0} 条`;
  } catch (error) {
    state.feedbackReview.records = [];
    state.feedbackReview.selectedRecordIds = [];
    state.feedbackReview.message = `读取审核样本失败：${error.message || error}`;
    showToast(state.feedbackReview.message, "error");
  } finally {
    state.feedbackReview.loading = false;
    renderFeedbackReviewPanel();
  }
}

async function loadFeedbackRecordDetail(recordId) {
  if (!recordId) return;
  state.feedbackReview.detailRecordId = recordId;
  state.feedbackReview.detailLoading = true;
  state.feedbackReview.detail = null;
  renderFeedbackReviewPanel();
  try {
    const params = new URLSearchParams({
      kind: state.feedbackReview.kind,
      record_id: recordId,
    });
    const response = await fetch(`/api/local-feedback-record-detail?${params.toString()}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "样本详情读取失败");
    state.feedbackReview.detail = payload;
  } catch (error) {
    state.feedbackReview.detail = { ok: false, error: error.message || String(error) };
    showToast(`样本详情读取失败：${error.message || error}`, "error");
  } finally {
    state.feedbackReview.detailLoading = false;
    renderFeedbackReviewPanel();
  }
}

async function updateFeedbackReviewBulk(action, options = {}) {
  const kind = state.feedbackReview.kind;
  const recordIds = Array.isArray(options.record_ids) ? options.record_ids : [];
  if (!recordIds.length && !options.filter) return;
  state.feedbackReview.bulkBusy = true;
  state.feedbackReview.message = `${feedbackBulkActionLabel(action)}中...`;
  renderFeedbackReviewPanel();
  try {
    const response = await fetch("/api/local-feedback-bulk-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        action,
        record_ids: recordIds,
        filter: options.filter || undefined,
        limit: options.limit || 50,
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || `${feedbackBulkActionLabel(action)}失败`);
    if (payload.summary) state.learningQuality = payload.summary;
    if (payload.summary) state.localFeedbackSummary = payload.summary;
    const skipped = Number(payload.skipped_count || 0);
    state.feedbackReview.message = `${feedbackBulkActionLabel(action)}完成：更新 ${payload.updated_count || 0} 条${skipped ? `，跳过 ${skipped} 条` : ""}`;
    state.feedbackReview.selectedRecordIds = [];
    renderLocalFeedbackSummary(state.localFeedbackSummary);
    await refreshFeedbackReview();
    refreshLearningQualitySummary();
    refreshLocalFeedbackImpactPreview();
  } catch (error) {
    state.feedbackReview.message = `${feedbackBulkActionLabel(action)}失败：${error.message || error}`;
    showToast(state.feedbackReview.message, "error");
    renderFeedbackReviewPanel();
  } finally {
    state.feedbackReview.bulkBusy = false;
    renderFeedbackReviewPanel();
  }
}

async function updateFeedbackReviewRecord(recordId, updates) {
  if (!recordId) return;
  const kind = state.feedbackReview.kind;
  state.feedbackReview.selectedRecordId = recordId;
  state.feedbackReview.message = "正在更新审核状态...";
  renderFeedbackReviewPanel();
  try {
    const response = await fetch("/api/local-feedback-record-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, record_id: recordId, updates }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "审核状态更新失败");
    if (payload.summary) state.localFeedbackSummary = payload.summary;
    state.feedbackReview.message = "审核状态已更新";
    renderLocalFeedbackSummary(state.localFeedbackSummary);
    await refreshFeedbackReview();
    if (state.feedbackReview.detailRecordId === recordId) loadFeedbackRecordDetail(recordId);
    refreshLearningQualitySummary();
  } catch (error) {
    state.feedbackReview.message = `审核状态更新失败：${error.message || error}`;
    showToast(state.feedbackReview.message, "error");
    renderFeedbackReviewPanel();
  } finally {
    state.feedbackReview.selectedRecordId = "";
    renderFeedbackReviewPanel();
  }
}

function renderCountList(rows, keyName, emptyText) {
  if (!Array.isArray(rows) || !rows.length) return `<div class="entity-empty">${escapeHtml(emptyText)}</div>`;
  return `<div class="learning-count-list">${rows
    .map((row) => `<div><span>${escapeHtml(row[keyName] || "unknown")}</span><strong>${escapeHtml(row.count ?? 0)}</strong></div>`)
    .join("")}</div>`;
}

function renderValueCountList(rows, emptyText) {
  if (!Array.isArray(rows) || !rows.length) return `<div class="entity-empty">${escapeHtml(emptyText)}</div>`;
  return `<div class="learning-count-list">${rows
    .map((row) => `<div><span>${escapeHtml(row.value || "unknown")}</span><strong>${escapeHtml(row.count ?? 0)}</strong></div>`)
    .join("")}</div>`;
}

function renderDiagnosticGroupList(groups, emptyText, titleKey = "source") {
  if (!Array.isArray(groups) || !groups.length) return `<div class="entity-empty">${escapeHtml(emptyText)}</div>`;
  return `<div class="learning-diagnostic-list">${groups
    .slice(0, 5)
    .map((group) => {
      const label = group[titleKey] || group.source || group.manual || "unknown";
      const recordButtons = (group.records || [])
        .slice(0, 4)
        .map((record) => {
          const recordLabel = `${record.project_id || "unknown"} #${record.segment_id ?? record.span_id ?? record.index}`;
          return `<button class="mini-btn" type="button" data-diagnostic-record-kind="${escapeHtml(record.kind || "style")}" data-diagnostic-record-id="${escapeHtml(record.record_id || "")}">${escapeHtml(recordLabel)}</button>`;
        })
        .join("");
      return `
        <div>
          <span>${escapeHtml(label || "空文本")}</span>
          <strong>${escapeHtml(group.count ?? 0)} 条</strong>
          <div class="diagnostic-record-actions">${recordButtons || `<span class="local-feedback-note">无可打开记录</span>`}</div>
        </div>
      `;
    })
    .join("")}</div>`;
}

function renderLearningDatasetDiagnostics(diagnostics) {
  const style = diagnostics?.style || {};
  const span = diagnostics?.span || {};
  const conflictCount = (style.conflict_group_count || 0) + (span.conflict_group_count || 0);
  const duplicateCount = (style.duplicate_group_count || 0) + (span.duplicate_group_count || 0);
  const mergeCount = (style.merge_candidate_group_count || 0) + (span.merge_candidate_group_count || 0);
  return `
    <section class="entity-section wide">
      <div class="entity-section-head"><h5>重复与冲突诊断</h5><span>本地只读检查</span></div>
      <div class="learning-ratio-list">
        <div><span>冲突组</span><strong>${escapeHtml(conflictCount)}</strong></div>
        <div><span>重复组</span><strong>${escapeHtml(duplicateCount)}</strong></div>
        <div><span>合并候选</span><strong>${escapeHtml(mergeCount)}</strong></div>
        <div><span>说明</span><strong>同源同机器基线但人工译法不同，需要优先复核。</strong></div>
      </div>
      <div class="prompt-preview-grid">
        <div>
          <span>ASS 冲突</span>
          ${renderDiagnosticGroupList(style.conflict_groups, "暂无 ASS 冲突。")}
        </div>
        <div>
          <span>Span 冲突</span>
          ${renderDiagnosticGroupList(span.conflict_groups, "暂无 Span 冲突。")}
        </div>
        <div>
          <span>ASS 重复</span>
          ${renderDiagnosticGroupList(style.duplicate_groups, "暂无 ASS 重复。")}
        </div>
        <div>
          <span>Span 重复</span>
          ${renderDiagnosticGroupList(span.duplicate_groups, "暂无 Span 重复。")}
        </div>
      </div>
      <p class="local-feedback-note">这些诊断不会修改 JSONL，也不会触发翻译请求。处理原则：冲突先人工复核，重复只保留质量最高、最稳定的一条进入 Prompt/Eval。</p>
    </section>
  `;
}

function learningStatusLabel(status) {
  const labels = {
    healthy: "健康",
    review_needed: "需要审核",
    eval_insufficient: "Eval 不足",
    span_insufficient: "Span 不足",
    unsafe: "风险样本",
  };
  return labels[status] || "待检查";
}

function learningStatusClass(status) {
  if (status === "healthy") return "ok";
  if (status === "unsafe") return "danger";
  if (status === "review_needed" || status === "eval_insufficient" || status === "span_insufficient") return "warn";
  return "muted";
}

function actionLabel(action) {
  const labels = {
    summarize: "运行 summarize",
    build_gold: "运行 build-gold",
    eval_style: "运行 eval-style",
    eval_span_style: "运行 eval-span-style",
  };
  return labels[action] || action;
}

function latestEvalTime(payload) {
  return payload?.quality?.latest_eval_at || payload?.eval?.created_at || payload?.span_eval?.created_at || "暂无";
}

function renderLearningHistory(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `<div class="entity-empty">暂无质量快照。运行 summarize 或 eval 后会写入轻量历史。</div>`;
  }
  return `
    <div class="learning-history-table">
      <div class="learning-history-row head">
        <span>时间</span><span>分数</span><span>ASS P/E</span><span>Span P/E</span><span>风险/信号</span>
      </div>
      ${rows
        .slice(0, 10)
        .map(
          (row) => `
            <div class="learning-history-row">
              <span>${escapeHtml(row.created_at || "")}</span>
              <strong>${escapeHtml(row.score ?? 0)}</strong>
              <span>${escapeHtml(`${row.style_prompt_count ?? 0}/${row.style_eval_count ?? 0}`)}</span>
              <span>${escapeHtml(`${row.span_prompt_count ?? 0}/${row.span_eval_count ?? 0}`)}</span>
              <span>${escapeHtml(`${formatPercent(row.style_unsafe_rate ?? 0)} / ${formatPercent(row.style_signal_rate ?? row.span_signal_rate ?? 0)}`)}</span>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function renderLocalFeedbackImpactPreviewCard() {
  const impact = state.localFeedbackImpact;
  if (!impact) {
    return `
      <section class="entity-section">
        <div class="entity-section-head"><h5>学习影响预览</h5><span>Prompt / Cache</span></div>
        <div class="entity-empty">还没有读取影响预览。</div>
        <div class="learning-action-buttons">
          <button class="mini-btn" type="button" data-learning-impact-refresh>刷新预览</button>
        </div>
      </section>
    `;
  }
  if (impact.ok === false) {
    return `
      <section class="entity-section">
        <div class="entity-section-head"><h5>学习影响预览</h5><span>读取失败</span></div>
        <div class="entity-alert">${escapeHtml(impact.error || "unknown error")}</div>
        <div class="learning-action-buttons">
          <button class="mini-btn" type="button" data-learning-impact-refresh>重新读取</button>
        </div>
      </section>
    `;
  }
  const injection = impact.prompt_injection_preview || {};
  const spanExamples = Array.isArray(injection.span_examples_preview) ? injection.span_examples_preview : [];
  return `
    <section class="entity-section">
      <div class="entity-section-head"><h5>学习影响预览</h5><span>Prompt / Cache</span></div>
      <div class="learning-ratio-list">
        <div><span>本地反馈</span><strong>${impact.enable_local_translation_feedback ? "已开启" : "未开启"}</strong></div>
        <div><span>ASS Prompt</span><strong>${escapeHtml(impact.style_prompt_count ?? 0)}</strong></div>
        <div><span>ASS Eval</span><strong>${escapeHtml(impact.style_eval_count ?? 0)}</strong></div>
        <div><span>Span Prompt</span><strong>${escapeHtml(impact.span_prompt_count ?? 0)}</strong></div>
        <div><span>Span Eval</span><strong>${escapeHtml(impact.span_eval_count ?? 0)}</strong></div>
        <div><span>注入 Span 示例</span><strong>${impact.would_inject_span_examples ? "会" : "不会"}</strong></div>
        <div><span>05a 缓存</span><strong>${impact.would_refresh_span_cache ? "样本变化会刷新" : "暂无 Span 示例影响"}</strong></div>
        <div><span>每次最多示例</span><strong>${escapeHtml(impact.max_span_examples_per_request ?? 3)}</strong></div>
        <div><span>Span hash</span><strong>${escapeHtml((impact.span_examples_hash || "").slice(0, 16))}</strong></div>
        <div><span>Style Prompt 估算</span><strong>${escapeHtml(injection.style_prompt_estimated_tokens ?? 0)} tokens</strong></div>
        <div><span>Span 示例估算</span><strong>${escapeHtml(injection.span_examples_estimated_tokens ?? 0)} tokens</strong></div>
      </div>
      ${(impact.notes || []).length ? `<div class="learning-quality-reasons">${impact.notes.map((note) => `<span>${escapeHtml(note)}</span>`).join("")}</div>` : ""}
      <div class="prompt-preview-grid">
        <div>
          <span>Style Prompt 预览</span>
          <pre class="feedback-json-preview">${escapeHtml(injection.style_prompt_preview || "暂无 style prompt。")}</pre>
        </div>
        <div>
          <span>已学习规则</span>
          ${
            Array.isArray(injection.style_guidelines_preview) && injection.style_guidelines_preview.length
              ? `<ul>${injection.style_guidelines_preview.slice(0, 8).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
              : `<p class="local-feedback-note">暂无 learned_style_guidelines.md 规则。</p>`
          }
        </div>
        <div class="wide">
          <span>Span 示例注入预览</span>
          ${
            spanExamples.length
              ? spanExamples.map((example, index) => `<pre class="feedback-json-preview">#${index + 1}\n${escapeHtml(JSON.stringify(example, null, 2))}</pre>`).join("")
              : `<p class="local-feedback-note">暂无可注入的 Span 示例。</p>`
          }
        </div>
      </div>
      <p class="local-feedback-note">这些操作只修改本地学习数据，不会启动字幕翻译，也不会增加翻译请求量。</p>
      <div class="learning-action-buttons">
        <button class="mini-btn" type="button" data-learning-impact-refresh>刷新预览</button>
      </div>
    </section>
  `;
}

function abEvalRecommendationLabel(value) {
  const labels = {
    local_feedback_helpful: "本地学习有效",
    neutral: "效果接近",
    possibly_harmful: "可能变差",
    insufficient_samples: "样本不足",
  };
  return labels[value] || "暂无结论";
}

function abEvalActionLabel(code) {
  const labels = {
    build_gold_or_review_eval: "先审核 Eval 样本并运行 build-gold，再做 A/B。",
    run_first_small_eval: "可以先运行一次 5 条小样本 A/B，建立基线。",
    keep_feedback_enabled_collect_more_gold: "本地学习有帮助：继续开启反馈，并补充更多 gold 样本验证稳定性。",
    review_high_signal_samples: "效果接近：优先复核高信号样本，避免只增加数量。",
    inspect_prompt_samples_before_more_runs: "学习可能变差：先检查 Prompt 样本质量，再继续评估。",
    increase_eval_sample_count: "样本不足：增加 Eval 样本或提高本次样本数后再判断。",
    add_span_eval_samples: "Span Eval 不足：审核一部分 Span 样本进入 Eval。",
    add_style_eval_samples: "ASS Eval 不足：审核一部分 ASS 样本进入 Eval。",
  };
  return labels[code] || code;
}

function renderAbEvalHistory(history) {
  const rows = Array.isArray(history?.latest_runs) ? history.latest_runs : [];
  if (!rows.length) return `<div class="entity-empty">暂无 A/B 历史。运行一次后会显示最近趋势。</div>`;
  return `
    <div class="learning-history-table compact">
      <div class="learning-history-row head">
        <span>时间</span><span>样本</span><span>结论</span><span>Style Δ</span><span>Span Δ</span>
      </div>
      ${rows
        .slice(0, 5)
        .map((row) => {
          const summary = row.summary || {};
          return `
            <div class="learning-history-row">
              <span>${escapeHtml(row.created_at || "")}</span>
              <strong>${escapeHtml(`${row.sample_kind || "mixed"} / ${row.sample_count ?? 0}`)}</strong>
              <span>${escapeHtml(abEvalRecommendationLabel(summary.recommendation))}</span>
              <span>${escapeHtml(summary.avg_style_feedback_delta ?? 0)}</span>
              <span>${escapeHtml(summary.avg_style_span_feedback_delta ?? 0)}</span>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderAbEvalReportPreview(report) {
  if (!report || report.available === false) {
    return `<div class="entity-empty">${escapeHtml(report?.message || "暂无 A/B 小样本评估报告。")}</div>`;
  }
  const summary = report.summary || {};
  const wins = summary.variant_wins || {};
  const samples = Array.isArray(report.samples) ? report.samples : [];
  return `
    <div class="learning-ratio-list">
      <div><span>最近时间</span><strong>${escapeHtml(report.created_at || "暂无")}</strong></div>
      <div><span>结论</span><strong>${escapeHtml(abEvalRecommendationLabel(summary.recommendation))}</strong></div>
      <div><span>Baseline 胜出</span><strong>${escapeHtml(wins.baseline ?? summary.baseline_win_count ?? 0)}</strong></div>
      <div><span>Style 胜出</span><strong>${escapeHtml(wins.style_feedback ?? summary.style_feedback_win_count ?? 0)}</strong></div>
      <div><span>Span 胜出</span><strong>${escapeHtml(wins.style_span_feedback ?? summary.style_span_feedback_win_count ?? 0)}</strong></div>
      <div><span>Style 平均变化</span><strong>${escapeHtml(summary.avg_style_feedback_delta ?? 0)}</strong></div>
      <div><span>Span 平均变化</span><strong>${escapeHtml(summary.avg_style_span_feedback_delta ?? 0)}</strong></div>
      <div><span>异常输出率</span><strong>${escapeHtml(formatPercent(summary.unsafe_output_rate ?? 0))}</strong></div>
    </div>
    ${
      samples.length
        ? `<div class="prompt-preview-grid">
            ${samples
              .slice(0, 3)
              .map(
                (sample) => `
                  <div>
                    <span>${escapeHtml(sample.kind || "sample")} · ${escapeHtml(sample.project_id || "")}</span>
                    <pre class="feedback-json-preview">${escapeHtml(
                      JSON.stringify(
                        {
                          source: sample.source,
                          manual_target: sample.manual_target,
                          best_variant: sample.best_variant,
                          delta_vs_baseline: sample.best_score_delta_vs_baseline,
                          metrics: sample.metrics,
                        },
                        null,
                        2
                      )
                    )}</pre>
                    ${
                      sample.record_id
                        ? `<button class="mini-btn" type="button" data-ab-eval-record-kind="${escapeHtml(sample.record_kind || sample.kind || "style")}" data-ab-eval-record-id="${escapeHtml(sample.record_id)}">打开样本详情</button>`
                        : ""
                    }
                  </div>
                `
              )
              .join("")}
          </div>`
        : ""
    }
  `;
}

function renderLocalFeedbackAbEvalCard() {
  const stateAb = state.localFeedbackAbEval || {};
  const preview = stateAb.preview || {};
  const report = stateAb.report || preview.latest_report || {};
  const history = preview.history || {};
  const recommendationCodes = Array.isArray(preview.recommendation_codes) ? preview.recommendation_codes : [];
  const sampleKind = stateAb.sampleKind || preview.sample_kind || "mixed";
  const sampleCount = Number(stateAb.sampleCount || preview.sample_count || 5);
  const actionClass = stateAb.status === "error" ? " error" : stateAb.status === "success" ? " ok" : "";
  return `
    <section class="entity-section wide">
      <div class="entity-section-head"><h5>小样本 A/B 评估</h5><span>手动模型调用 / 不跑完整流程</span></div>
      <div class="ab-eval-controls">
        <label>
          <span>样本类型</span>
          <select data-ab-eval-sample-kind ${stateAb.status === "running" ? "disabled" : ""}>
            <option value="mixed" ${sampleKind === "mixed" ? "selected" : ""}>ASS + Span 混合</option>
            <option value="style" ${sampleKind === "style" ? "selected" : ""}>只评估 ASS</option>
            <option value="span" ${sampleKind === "span" ? "selected" : ""}>只评估 Span</option>
          </select>
        </label>
        <label>
          <span>样本数</span>
          <input data-ab-eval-sample-count type="number" min="1" max="10" value="${escapeHtml(sampleCount)}" ${stateAb.status === "running" ? "disabled" : ""} />
        </label>
      </div>
      ${
        preview.ok === false
          ? `<div class="entity-alert">${escapeHtml(preview.error || "A/B 预估读取失败")}</div>`
          : `<div class="learning-ratio-list">
              <div><span>ASS gold</span><strong>${escapeHtml(preview.eligible_style_count ?? 0)}</strong></div>
              <div><span>Span gold</span><strong>${escapeHtml(preview.eligible_span_count ?? 0)}</strong></div>
              <div><span>默认样本</span><strong>${escapeHtml(preview.default_sample_count ?? 5)}</strong></div>
              <div><span>本次样本</span><strong>${escapeHtml(preview.selected_sample_count ?? 0)}</strong></div>
              <div><span>预计请求</span><strong>${escapeHtml(preview.estimated_request_count ?? 0)} / ${escapeHtml(preview.max_request_count ?? 30)}</strong></div>
              <div><span>Prompt 估算</span><strong>${escapeHtml(preview.estimated_prompt_tokens ?? 0)} tokens</strong></div>
              <div><span>可运行</span><strong>${preview.can_run ? "可以" : "暂不可"}</strong></div>
              <div><span>变体</span><strong>${escapeHtml((preview.variants || []).join(" / ") || "baseline / style / span")}</strong></div>
            </div>`
      }
      ${(preview.warnings || []).length ? `<div class="learning-quality-reasons">${preview.warnings.map((note) => `<span>${escapeHtml(note)}</span>`).join("")}</div>` : ""}
      ${
        recommendationCodes.length
          ? `<div class="learning-quality-reasons">${recommendationCodes.map((code) => `<span>${escapeHtml(abEvalActionLabel(code))}</span>`).join("")}</div>`
          : ""
      }
      <p class="local-feedback-note">此操作会调用翻译模型，但不会启动完整字幕流程，不会修改学习 JSONL。05/05a 只作为机器基线，不作为人工学习目标。</p>
      <div class="learning-action-buttons">
        <button class="mini-btn" type="button" data-ab-eval-refresh ${stateAb.status === "running" ? "disabled" : ""}>刷新预估</button>
        <button class="mini-btn" type="button" data-ab-eval-run ${stateAb.status === "running" || preview.can_run === false ? "disabled" : ""}>运行 ${escapeHtml(sampleCount)} 条小样本 A/B</button>
        <button class="mini-btn" type="button" data-ab-eval-report ${stateAb.status === "running" ? "disabled" : ""}>查看最新报告</button>
      </div>
      <span class="local-feedback-action-status${actionClass}">${escapeHtml(stateAb.message || "等待手动运行。")}</span>
      ${renderAbEvalHistory(history)}
      ${renderAbEvalReportPreview(report)}
    </section>
  `;
}

async function refreshLocalFeedbackImpactPreview() {
  try {
    const response = await fetch("/api/local-feedback-impact-preview");
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) throw new Error(payload?.error || "学习影响预览读取失败");
    state.localFeedbackImpact = payload;
  } catch (error) {
    state.localFeedbackImpact = { ok: false, error: error.message || String(error) };
  }
  renderLearningQualityPanel();
}

async function refreshLocalFeedbackAbEvalPreview() {
  try {
    const params = new URLSearchParams({
      sample_kind: state.localFeedbackAbEval.sampleKind || "mixed",
      sample_count: String(Math.max(1, Math.min(10, Number(state.localFeedbackAbEval.sampleCount || 5)))),
    });
    const response = await fetch(`/api/local-feedback-ab-eval-preview?${params.toString()}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) throw new Error(payload?.error || "A/B 预估读取失败");
    state.localFeedbackAbEval.preview = payload;
    if (payload.latest_report) state.localFeedbackAbEval.report = payload.latest_report;
    if (!state.localFeedbackAbEval.message) state.localFeedbackAbEval.message = "A/B 预估已刷新。";
  } catch (error) {
    state.localFeedbackAbEval.preview = { ok: false, error: error.message || String(error) };
    state.localFeedbackAbEval.message = `A/B 预估读取失败：${error.message || error}`;
  }
  renderLearningQualityPanel();
}

async function loadLocalFeedbackAbEvalReport() {
  state.localFeedbackAbEval.status = "loading";
  state.localFeedbackAbEval.message = "正在读取最新 A/B 报告...";
  renderLearningQualityPanel();
  try {
    const response = await fetch("/api/local-feedback-ab-eval-report");
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) throw new Error(payload?.error || "A/B 报告读取失败");
    state.localFeedbackAbEval.report = payload;
    state.localFeedbackAbEval.status = "success";
    state.localFeedbackAbEval.message = payload.available ? "已读取最新 A/B 报告。" : "暂无 A/B 报告。";
  } catch (error) {
    state.localFeedbackAbEval.status = "error";
    state.localFeedbackAbEval.message = `A/B 报告读取失败：${error.message || error}`;
    showToast(state.localFeedbackAbEval.message, "error");
  }
  renderLearningQualityPanel();
}

async function runLocalFeedbackAbEval() {
  const sampleCount = Math.max(1, Math.min(10, Number(state.localFeedbackAbEval.sampleCount || 5)));
  const sampleKind = state.localFeedbackAbEval.sampleKind || "mixed";
  state.localFeedbackAbEval.status = "running";
  state.localFeedbackAbEval.message = `正在运行 ${sampleCount} 条小样本 A/B；这会调用翻译模型，但不会启动完整字幕流程。`;
  renderLearningQualityPanel();
  try {
    const response = await fetch("/api/local-feedback-ab-eval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sample_kind: sampleKind,
        sample_count: sampleCount,
        variants: ["baseline", "style_feedback", "style_span_feedback"],
        config: readFormConfig(),
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "A/B 小样本评估失败");
    state.localFeedbackAbEval.report = payload.report || null;
    state.localFeedbackAbEval.preview = payload.preview || state.localFeedbackAbEval.preview;
    if (payload.summary) state.learningQuality = payload.summary;
    state.localFeedbackAbEval.status = "success";
    const recommendation = payload.report?.summary?.recommendation || "";
    state.localFeedbackAbEval.message = `A/B 小样本评估完成：${abEvalRecommendationLabel(recommendation)}。`;
    showToast(state.localFeedbackAbEval.message);
  } catch (error) {
    state.localFeedbackAbEval.status = "error";
    state.localFeedbackAbEval.message = `A/B 小样本评估失败：${error.message || error}`;
    showToast(state.localFeedbackAbEval.message, "error");
  }
  renderLearningQualityPanel();
}

function jumpToFeedbackReview(kind) {
  state.feedbackReview.kind = kind === "span" ? "span" : "style";
  state.feedbackReview.status = "pending";
  document.querySelectorAll(".tab, .nav-item").forEach((node) => {
    const active = node.dataset.panel === "feedback-review";
    node.classList.toggle("active", active);
    node.setAttribute("aria-selected", active ? "true" : "false");
    if (active) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  document.querySelectorAll(".workspace-panel").forEach((node) => {
    node.classList.toggle("active", node.dataset.panel === "feedback-review");
  });
  refreshFeedbackReview();
  scrollToWorkspaceDetails();
}

async function openDiagnosticFeedbackRecord(kind, recordId) {
  if (!recordId) return;
  state.feedbackReview.kind = kind === "span" ? "span" : "style";
  state.feedbackReview.status = "all";
  state.feedbackReview.detailRecordId = recordId;
  document.querySelectorAll(".tab, .nav-item").forEach((node) => {
    const active = node.dataset.panel === "feedback-review";
    node.classList.toggle("active", active);
    node.setAttribute("aria-selected", active ? "true" : "false");
    if (active) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  document.querySelectorAll(".workspace-panel").forEach((node) => {
    node.classList.toggle("active", node.dataset.panel === "feedback-review");
  });
  await refreshFeedbackReview();
  await loadFeedbackRecordDetail(recordId);
  scrollToWorkspaceDetails();
}

async function runLocalFeedbackAction(action) {
  state.learningQualityAction = { status: "running", action, message: `${actionLabel(action)} 中...` };
  renderLearningQualityPanel();
  try {
    const response = await fetch("/api/local-feedback-action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || `${actionLabel(action)} 失败`);
    state.learningQuality = payload.summary || state.learningQuality;
    state.learningQualityAction = { status: "success", action, message: `${actionLabel(action)} 已完成；已刷新质量快照。` };
    if (payload.summary) state.localFeedbackSummary = payload.summary;
    renderLocalFeedbackSummary(state.localFeedbackSummary);
    showToast(state.learningQualityAction.message);
  } catch (error) {
    state.learningQualityAction = { status: "error", action, message: `${actionLabel(action)} 失败：${error.message || error}` };
    showToast(state.learningQualityAction.message, "error");
  }
  renderLearningQualityPanel();
}

function renderLearningQualityPanel() {
  const root = el("learningQualityPanel");
  if (!root) return;
  const payload = state.learningQuality;
  if (!payload) {
    root.innerHTML = `
      <div class="entity-panel">
        <div class="entity-panel-head">
          <div>
            <h4>学习质量面板</h4>
            <p>点击刷新后读取本地反馈数据集、Eval 报告和已学习规则。</p>
          </div>
        </div>
      </div>
    `;
    return;
  }
  if (payload.ok === false) {
    root.innerHTML = `<div class="entity-alert">学习质量读取失败：${escapeHtml(payload.error || "unknown error")}</div>`;
    return;
  }
  const counts = payload.counts || {};
  const evalMetrics = payload.eval?.metrics || {};
  const spanMetrics = payload.span_eval?.metrics || {};
  const pending = payload.pending || {};
  const quality = payload.quality || {};
  const coverage = payload.coverage || {};
  const risk = payload.risk || {};
  const distributions = payload.distributions || {};
  const action = state.learningQualityAction || {};
  const actionClass = action.status === "error" ? " error" : action.status === "success" ? " ok" : "";
  const status = quality.overall_status || "unknown";
  const statusClass = learningStatusClass(status);
  const allRecommendations = [...(payload.recommendations?.style || []), ...(payload.recommendations?.span || [])];
  const guidelineExpanded = Boolean(state.learningGuidelinesExpanded);
  const reviewSuggestions = feedbackSuggestionCounts(state.feedbackReview.kind === "span" ? state.feedbackReview.records || [] : []);
  root.innerHTML = `
    <section class="learning-quality-hero ${statusClass}">
      <div>
        <div class="learning-quality-title-row">
          <span class="entity-chip ${statusClass}">${escapeHtml(learningStatusLabel(status))}</span>
          <strong>${escapeHtml(quality.score ?? 0)} / 100</strong>
        </div>
        <h4>学习质量诊断</h4>
        <p>${escapeHtml((quality.reasons || [])[0] || "正在读取本地学习质量。")}</p>
        <div class="learning-quality-reasons">
          ${(quality.reasons || []).slice(0, 4).map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}
        </div>
      </div>
      <div class="learning-quality-meta">
        <div><span>数据集</span><strong>${escapeHtml(payload.dataset_dir || "")}</strong></div>
        <div><span>最近 Eval</span><strong>${escapeHtml(latestEvalTime(payload))}</strong></div>
        <div><span>反馈注入</span><strong>${escapeHtml(state.config?.enable_local_translation_feedback ? "已开启" : "未开启")}</strong></div>
        <div><span>Prompt / Eval</span><strong>${escapeHtml(`${(counts.style_learning_count ?? 0) + (counts.span_style_learning_count ?? 0)} / ${(counts.style_gold_count ?? 0) + (counts.span_eval_count ?? 0)}`)}</strong></div>
      </div>
    </section>

    <div class="learning-quality-grid">
      <div class="entity-metric"><span>ASS 编辑样本</span><strong>${escapeHtml(counts.translation_edit_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>ASS Prompt 样本</span><strong>${escapeHtml(counts.style_learning_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>ASS Eval 样本</span><strong>${escapeHtml(counts.style_gold_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>Span 样本</span><strong>${escapeHtml(counts.span_translation_example_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>Span Prompt 样本</span><strong>${escapeHtml(counts.span_style_learning_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>Span Eval 样本</span><strong>${escapeHtml(counts.span_eval_count ?? 0)}</strong></div>
      <div class="entity-metric"><span>待审 ASS</span><strong>${escapeHtml(pending.style ?? 0)}</strong></div>
      <div class="entity-metric"><span>待审 Span</span><strong>${escapeHtml(pending.span ?? 0)}</strong></div>
      <div class="entity-metric"><span>ASS 不安全率</span><strong>${escapeHtml(formatPercent(evalMetrics.unsafe_sample_rate ?? 0))}</strong></div>
      <div class="entity-metric"><span>ASS 信号率</span><strong>${escapeHtml(formatPercent(evalMetrics.semantic_or_style_signal_rate ?? 0))}</strong></div>
      <div class="entity-metric"><span>Span 重分配率</span><strong>${escapeHtml(formatPercent(spanMetrics.semantic_reallocation_rate ?? 0))}</strong></div>
      <div class="entity-metric"><span>Span 碎句补全率</span><strong>${escapeHtml(formatPercent(spanMetrics.fragment_completion_rate ?? 0))}</strong></div>
      <div class="entity-metric"><span>ASS Prompt 比例</span><strong>${escapeHtml(formatPercent(coverage.style_prompt_ratio ?? 0))}</strong></div>
      <div class="entity-metric"><span>ASS Eval 比例</span><strong>${escapeHtml(formatPercent(coverage.style_eval_ratio ?? 0))}</strong></div>
      <div class="entity-metric"><span>Span Prompt 比例</span><strong>${escapeHtml(formatPercent(coverage.span_prompt_ratio ?? 0))}</strong></div>
      <div class="entity-metric"><span>Span Eval 比例</span><strong>${escapeHtml(formatPercent(coverage.span_eval_ratio ?? 0))}</strong></div>
    </div>

    <div class="learning-quality-sections">
      <section class="entity-section">
        <div class="entity-section-head"><h5>Span 短板行动</h5><span>审核 / Prompt / Eval</span></div>
        <div class="learning-ratio-list">
          <div><span>待审 Span</span><strong>${escapeHtml(pending.span ?? 0)}</strong></div>
          <div><span>Span Prompt</span><strong>${escapeHtml(counts.span_style_learning_count ?? 0)}</strong></div>
          <div><span>Span Eval</span><strong>${escapeHtml(counts.span_eval_count ?? 0)}</strong></div>
          <div><span>推荐 Prompt</span><strong>${escapeHtml(reviewSuggestions.use_for_prompt || 0)}</strong></div>
          <div><span>推荐 Eval</span><strong>${escapeHtml(reviewSuggestions.use_for_eval || 0)}</strong></div>
          <div><span>高风险 / bad-alignment</span><strong>${escapeHtml((risk.span_high_risk_count ?? 0) + (risk.bad_alignment_count ?? 0))}</strong></div>
        </div>
        <p class="local-feedback-note">如果推荐数量为 0，先点击“去审核待审 Span”刷新审核列表。批量推荐会跳过 high-risk 和 bad_alignment。</p>
        <div class="learning-action-buttons">
          <button class="mini-btn" type="button" data-learning-jump="span">去审核待审 Span</button>
          <button class="mini-btn" type="button" data-learning-suggested-span="use_for_prompt">按推荐加入 Prompt</button>
          <button class="mini-btn" type="button" data-learning-suggested-span="use_for_eval">按推荐加入 Eval</button>
          <button class="mini-btn" type="button" data-learning-action="eval_span_style">运行 Span Eval</button>
        </div>
      </section>
      ${renderLocalFeedbackImpactPreviewCard()}
      ${renderLocalFeedbackAbEvalCard()}
      ${renderLearningDatasetDiagnostics(payload.dataset_diagnostics)}
      <section class="entity-section">
        <div class="entity-section-head"><h5>样本覆盖</h5><span>Prompt / Eval / Pending</span></div>
        <div class="learning-ratio-list">
          <div><span>ASS Prompt</span><strong>${escapeHtml(formatPercent(coverage.style_prompt_ratio ?? 0))}</strong></div>
          <div><span>ASS Eval</span><strong>${escapeHtml(formatPercent(coverage.style_eval_ratio ?? 0))}</strong></div>
          <div><span>ASS 待审</span><strong>${escapeHtml(formatPercent(coverage.style_pending_ratio ?? 0))}</strong></div>
          <div><span>Span Prompt</span><strong>${escapeHtml(formatPercent(coverage.span_prompt_ratio ?? 0))}</strong></div>
          <div><span>Span Eval</span><strong>${escapeHtml(formatPercent(coverage.span_eval_ratio ?? 0))}</strong></div>
          <div><span>Span 待审</span><strong>${escapeHtml(formatPercent(coverage.span_pending_ratio ?? 0))}</strong></div>
        </div>
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>风险与安全</h5><span>High / Medium / Bad</span></div>
        <div class="learning-ratio-list">
          <div><span>ASS 高风险</span><strong>${escapeHtml(risk.style_high_risk_count ?? 0)}</strong></div>
          <div><span>ASS 中风险</span><strong>${escapeHtml(risk.style_medium_risk_count ?? 0)}</strong></div>
          <div><span>Span 高风险</span><strong>${escapeHtml(risk.span_high_risk_count ?? 0)}</strong></div>
          <div><span>Span 中风险</span><strong>${escapeHtml(risk.span_medium_risk_count ?? 0)}</strong></div>
          <div><span>bad-example</span><strong>${escapeHtml(risk.bad_example_count ?? 0)}</strong></div>
          <div><span>bad-alignment</span><strong>${escapeHtml(risk.bad_alignment_count ?? 0)}</strong></div>
        </div>
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>ASS 项目来源</h5><span>Top 8</span></div>
        ${renderCountList(payload.projects?.style, "project_id", "暂无 ASS 来源统计")}
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>Span 项目来源</h5><span>Top 8</span></div>
        ${renderCountList(payload.projects?.span, "project_id", "暂无 Span 来源统计")}
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>ASS 编辑标签</h5><span>Top 12</span></div>
        ${renderCountList(payload.tags?.style, "tag", "暂无 ASS 标签统计")}
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>Span 编辑标签</h5><span>Top 12</span></div>
        ${renderCountList(payload.tags?.span, "tag", "暂无 Span 标签统计")}
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>ASS 推荐用途</h5><span>review / prompt / eval</span></div>
        ${renderValueCountList(distributions.style_recommendation, "暂无 ASS 推荐用途统计")}
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>Span 推荐用途</h5><span>review / prompt / eval</span></div>
        ${renderValueCountList(distributions.span_recommendation, "暂无 Span 推荐用途统计")}
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>ASS 风险分布</h5><span>low / medium / high</span></div>
        ${renderValueCountList(distributions.style_risk, "暂无 ASS 风险统计")}
      </section>
      <section class="entity-section">
        <div class="entity-section-head"><h5>Span 风险分布</h5><span>low / medium / high</span></div>
        ${renderValueCountList(distributions.span_risk, "暂无 Span 风险统计")}
      </section>
      <section class="entity-section wide">
        <div class="entity-section-head"><h5>趋势快照</h5><span>最近 10 次</span></div>
        ${renderLearningHistory(payload.history)}
      </section>
      <section class="entity-section wide">
        <div class="entity-section-head"><h5>下一步行动</h5><span>不会启动字幕翻译</span></div>
        <div class="learning-action-panel">
          <div class="learning-action-copy">
            <strong>建议</strong>
            ${
              allRecommendations.length
                ? `<ul>${allRecommendations.slice(0, 5).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
                : `<p>当前没有额外建议。</p>`
            }
            <p>05/05a 仅作为机器基线，不作为人工学习目标；这些操作不会增加翻译请求量。</p>
          </div>
          <div class="learning-action-buttons">
            <button class="mini-btn" type="button" data-learning-jump="style">去审核待审 ASS</button>
            <button class="mini-btn" type="button" data-learning-jump="span">去审核待审 Span</button>
            <button class="mini-btn" type="button" data-learning-action="summarize">运行 summarize</button>
            <button class="mini-btn" type="button" data-learning-action="build_gold">运行 build-gold</button>
            <button class="mini-btn" type="button" data-learning-action="eval_style">运行 eval-style</button>
            <button class="mini-btn" type="button" data-learning-action="eval_span_style">运行 eval-span-style</button>
            <button id="toggleLearningGuidelinesBtn" class="mini-btn" type="button">${guidelineExpanded ? "收起规则" : "查看规则"}</button>
          </div>
          <span class="local-feedback-action-status${actionClass}">${escapeHtml(action.message || "等待操作。")}</span>
        </div>
      </section>
    </div>
    <div class="learning-guideline-row ${guidelineExpanded ? "" : "hidden"}">
      <div class="local-feedback-guidelines">
        <strong>ASS 已学习规则</strong>
        ${
          Array.isArray(payload.guidelines) && payload.guidelines.length
            ? `<ul>${payload.guidelines.slice(0, 6).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
            : `<p>暂无 ASS 规则预览。</p>`
        }
      </div>
      <div class="local-feedback-guidelines">
        <strong>Span 已学习规则</strong>
        ${
          Array.isArray(payload.span_guidelines) && payload.span_guidelines.length
            ? `<ul>${payload.span_guidelines.slice(0, 6).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
            : `<p>暂无 Span 规则预览。</p>`
        }
      </div>
    </div>
  `;
  root.querySelectorAll("[data-learning-jump]").forEach((button) => {
    button.addEventListener("click", () => jumpToFeedbackReview(button.getAttribute("data-learning-jump") || "style"));
  });
  root.querySelectorAll("[data-learning-action]").forEach((button) => {
    button.addEventListener("click", () => runLocalFeedbackAction(button.getAttribute("data-learning-action") || ""));
  });
  root.querySelectorAll("[data-learning-suggested-span]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestedAction = button.getAttribute("data-learning-suggested-span") || "";
      state.feedbackReview.kind = "span";
      state.feedbackReview.status = "pending";
      updateFeedbackReviewBulk(suggestedAction, {
        filter: {
          status: "pending",
          suggested_actions: [suggestedAction],
          exclude_tags: ["bad_alignment", "bad_example"],
        },
      });
    });
  });
  root.querySelectorAll("[data-learning-impact-refresh]").forEach((button) => {
    button.addEventListener("click", () => refreshLocalFeedbackImpactPreview());
  });
  root.querySelectorAll("[data-ab-eval-sample-kind]").forEach((select) => {
    select.addEventListener("change", () => {
      state.localFeedbackAbEval.sampleKind = select.value || "mixed";
      refreshLocalFeedbackAbEvalPreview();
    });
  });
  root.querySelectorAll("[data-ab-eval-sample-count]").forEach((input) => {
    input.addEventListener("change", () => {
      const value = Math.max(1, Math.min(10, Number(input.value || 5)));
      state.localFeedbackAbEval.sampleCount = value;
      input.value = String(value);
      refreshLocalFeedbackAbEvalPreview();
    });
  });
  root.querySelectorAll("[data-ab-eval-refresh]").forEach((button) => {
    button.addEventListener("click", () => refreshLocalFeedbackAbEvalPreview());
  });
  root.querySelectorAll("[data-ab-eval-run]").forEach((button) => {
    button.addEventListener("click", () => runLocalFeedbackAbEval());
  });
  root.querySelectorAll("[data-ab-eval-report]").forEach((button) => {
    button.addEventListener("click", () => loadLocalFeedbackAbEvalReport());
  });
  root.querySelectorAll("[data-ab-eval-record-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openDiagnosticFeedbackRecord(
        button.getAttribute("data-ab-eval-record-kind") || "style",
        button.getAttribute("data-ab-eval-record-id") || "",
      );
    });
  });
  root.querySelectorAll("[data-diagnostic-record-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openDiagnosticFeedbackRecord(
        button.getAttribute("data-diagnostic-record-kind") || "style",
        button.getAttribute("data-diagnostic-record-id") || "",
      );
    });
  });
  el("toggleLearningGuidelinesBtn")?.addEventListener("click", () => {
    state.learningGuidelinesExpanded = !state.learningGuidelinesExpanded;
    renderLearningQualityPanel();
  });
}

async function refreshLearningQualitySummary() {
  try {
    const response = await fetch("/api/learning-quality-summary");
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) throw new Error(payload?.error || "学习质量读取失败");
    state.learningQuality = payload;
  } catch (error) {
    state.learningQuality = { ok: false, error: error.message || String(error) };
  }
  renderLearningQualityPanel();
  refreshLocalFeedbackAbEvalPreview();
}

function humanRunStateLabel(stageKey, title) {
  const flow = state.flowControl || {};
  if (flow.paused) return "暂停中";
  if (flow.pause_requested) return "等待暂停";
  if (title) return title;
  const fallbackMap = {
    idle: "等待中",
    complete: "完成",
    error: "错误",
    recovered_state: "已恢复",
  };
  return fallbackMap[String(stageKey || "idle")] || "等待中";
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
    state.selectedVideoProject = null;
    state.selectedVideoProjectPath = null;
    state.selectedMediaInfo = null;
    el("selectedVideoName").textContent = "未选择视频";
    el("selectedVideoMeta").textContent = "请添加视频后开始处理。";
    const commandName = el("commandSelectedVideoName");
    if (commandName) commandName.textContent = "未选择视频";
    renderCommandContext();
    renderMediaAlert();
    renderInputAssStatus();
    return;
  }
  const previousPath = state.selectedVideo?.path;
  const matched = videos.find((video) => video.path === previousPath);
  state.selectedVideo = matched || videos[0];
  state.selectedVideoProject = findProjectForSelectedVideo();
  state.selectedVideoProjectPath = state.selectedVideoProject?.path || null;
  el("selectedVideoName").textContent = state.selectedVideo.name;
  el("selectedVideoMeta").textContent = `输入路径：${state.selectedVideo.path}`;
  const commandName = el("commandSelectedVideoName");
  if (commandName) commandName.textContent = state.selectedVideo.name;
  renderCommandContext();
  if (state.selectedVideo.path !== previousPath || !state.selectedMediaInfo) {
    inspectSelectedVideo();
  }
  renderInputAssStatus();
  renderLocalFeedbackSummary(state.localFeedbackSummary);
}

function renderVideos(videos) {
  state.videos = videos;
  syncSelectedVideo(videos);
  state.selectedVideoProject = findProjectForSelectedVideo();
  state.selectedVideoProjectPath = state.selectedVideoProject?.path || null;
  const root = el("videoList");
  root.innerHTML = "";
  const toggleBtn = el("toggleInputListBtn");
  if (toggleBtn) {
    toggleBtn.textContent = state.inputListCollapsed ? "展开全部 Input" : "只显示当前 Input";
  }

  const visibleVideos = state.inputListCollapsed
    ? videos.filter((video) => video.path === state.selectedVideo?.path).slice(0, 1)
    : videos;

  visibleVideos.forEach((video) => {
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
      scrollToWorkspaceDetails();
    });
    root.appendChild(item);
    revealNewNode("videos", video.path || video.name, item, root.children.length - 1);
  });

  if (!videos.length) {
    root.innerHTML = `<div class="stage-item empty-card"><strong>暂无输入视频</strong><div class="meta-row"><span>点击“添加 Input”或下载视频后会出现在这里。</span></div></div>`;
    revealChildren(root, ".stage-item");
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
    revealNewNode("stage", `${entry.stage || ""}:${entry.title || ""}:${entry.description || ""}`, node, root.children.length - 1);
  });
  if (!entries.length) {
    root.innerHTML = `<div class="stage-item empty-card"><strong>暂无运行日志</strong><div class="meta-row"><span>流程启动后会在这里展示结构化阶段摘要。</span></div></div>`;
    revealChildren(root, ".stage-item");
  }
}

function renderQueue(queue) {
  const root = el("queueList");
  root.innerHTML = "";
  const hasJobs = Array.isArray(state.jobs) && state.jobs.length > 0;
  const counts = (state.jobs || []).reduce(
    (acc, job) => {
      const status = String(job.status || "queued");
      if (status === "running") acc.running += 1;
      else if (status === "paused") acc.paused += 1;
      else if (status === "failed") acc.failed += 1;
      else if (status === "succeeded" || status === "succeeded_with_qa_issues") acc.done += 1;
      else acc.waiting += 1;
      return acc;
    },
    { waiting: hasJobs ? 0 : queue?.length || 0, running: 0, paused: 0, failed: 0, done: 0 }
  );
  const summary = document.createElement("div");
  summary.className = "queue-summary";
  summary.innerHTML = `
    <span>等待 ${counts.waiting}</span>
    <span>运行 ${counts.running}</span>
    <span>暂停 ${counts.paused}</span>
    <span>失败 ${counts.failed}</span>
    <span>完成 ${counts.done}</span>
  `;
  root.appendChild(summary);
  (queue || []).forEach((item, index) => {
    const node = document.createElement("div");
    node.className = "stage-item";
    node.innerHTML = `
      <div><strong>${index + 1}. ${item.name}</strong></div>
      <div class="meta-row"><span>${item.managed ? "本次会话" : "初始输入"}</span><span>${bytes(item.size || 0)}</span></div>
      <div class="path-note">${item.path}</div>
    `;
    root.appendChild(node);
    revealNewNode("queue", item.path || item.name || String(index), node, root.children.length - 1);
  });
  if (!queue || !queue.length) {
    root.innerHTML += `<div class="stage-item empty-card"><strong>队列为空</strong><div class="meta-row"><span>下载到队列或添加 Input 后会显示在这里。</span></div></div>`;
    revealChildren(root, ".stage-item");
  }
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function shortJobId(value) {
  const id = String(value || "");
  return id ? id.slice(0, 8) : "";
}

function jobStatusLabel(status) {
  return jobStatusLabels[String(status || "")] || String(status || "未知");
}

function jobInputName(job) {
  const input = String(job?.input_path || "");
  return input ? input.split(/[\\/]/).pop() : "未记录输入";
}

function renderJobs(jobs, activeJob) {
  const activeRoot = el("activeJobCard");
  const listRoot = el("jobList");
  if (!activeRoot || !listRoot) return;

  const visibleJobs = Array.isArray(jobs) ? jobs.slice(0, 8) : [];
  const active = activeJob && typeof activeJob === "object" ? activeJob : null;

  if (active) {
    const progress = Math.max(0, Math.min(100, Number(active.progress || 0)));
    activeRoot.classList.remove("empty");
    activeRoot.innerHTML = `
      <div class="job-title-row">
        <strong>${escapeHtml(jobInputName(active))}</strong>
        <span class="job-status status-${escapeHtml(String(active.status || ""))}">${escapeHtml(jobStatusLabel(active.status))}</span>
      </div>
      <div class="job-progress">
        <div class="job-progress-fill" style="width:${progress}%"></div>
      </div>
      <div class="job-meta-grid">
        <div><span>阶段</span><strong>${escapeHtml(active.current_stage || "idle")}</strong></div>
        <div><span>进度</span><strong>${progress}%</strong></div>
        <div><span>任务 ID</span><strong>${escapeHtml(shortJobId(active.id))}</strong></div>
        <div><span>更新</span><strong>${escapeHtml(formatDateTime(active.updated_at))}</strong></div>
      </div>
      ${active.output_dir ? `<div class="path-note">${escapeHtml(active.output_dir)}</div>` : ""}
    `;
  } else {
    activeRoot.classList.add("empty");
    activeRoot.innerHTML = `<strong>当前没有后端任务</strong><div class="meta-row"><span>启动流程后，worker 的真实状态会显示在这里。</span></div>`;
  }

  listRoot.innerHTML = "";
  visibleJobs.forEach((job) => {
    const node = document.createElement("div");
    node.className = "job-item" + (active?.id && active.id === job.id ? " active" : "");
    node.innerHTML = `
      <div class="job-title-row">
        <strong>${escapeHtml(jobInputName(job))}</strong>
        <span class="job-status status-${escapeHtml(String(job.status || ""))}">${escapeHtml(jobStatusLabel(job.status))}</span>
      </div>
      <div class="meta-row">
        <span>${escapeHtml(shortJobId(job.id))}</span>
        <span>${Math.max(0, Math.min(100, Number(job.progress || 0)))}%</span>
      </div>
      <div class="path-note">${escapeHtml(job.current_stage || "")}${job.updated_at ? ` · ${escapeHtml(formatDateTime(job.updated_at))}` : ""}</div>
    `;
    listRoot.appendChild(node);
    revealNewNode("jobs", job.id || `${job.input_path || ""}:${job.updated_at || ""}`, node, listRoot.children.length - 1);
  });

  if (!visibleJobs.length) {
    listRoot.innerHTML = `<div class="stage-item empty-card"><strong>暂无历史任务</strong><div class="meta-row"><span>后端 JobStore 记录会在任务创建后出现在这里。</span></div></div>`;
    revealChildren(listRoot, ".stage-item");
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
  const activeChunk = chunks.find((chunk) => chunk.status === "running") || chunks.find((chunk) => chunk.index === translationPhase.current) || chunks[0];
  const retryCount = chunks.reduce((total, chunk) => total + Number(chunk.fallback_count || chunk.retry_count || chunk.retries || 0), 0);
  panel.innerHTML = `
    <div class="chunk-panel-head">
      <strong>翻译 Chunk</strong>
      <span>${translationPhase.current || 0}/${translationPhase.total || chunks.length}</span>
    </div>
    <div class="chunk-summary">
      <span>当前 ${activeChunk?.index ?? translationPhase.current ?? 0}</span>
      <span>失败重试 ${retryCount}</span>
      <span>当前耗时 ${translationPhase.elapsed_seconds ? seconds(translationPhase.elapsed_seconds) : "-"}</span>
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
      if (phase.enhancement_mode && phase.enhancement_mode !== "off") stats.push(`增强 ${phase.enhancement_mode}`);
      if (phase.gain_db) stats.push(`+${Number(phase.gain_db).toFixed(1)} dB`);
    }

    if (key === "asr") {
      if (phase.current || phase.total) stats.push(`块 ${phase.current || 0}/${phase.total || 0}`);
      if (phase.segment_count) stats.push(`段数 ${phase.segment_count}`);
      if (phase.processed_seconds || phase.duration_seconds) stats.push(`${seconds(phase.processed_seconds || 0)} / ${seconds(phase.duration_seconds || 0)}`);
      if (phase.audio_mode && phase.audio_mode !== "off") stats.push(`音频 ${phase.audio_mode}`);
      if (phase.vad_mode) stats.push(`VAD ${phase.vad_mode}${phase.vad_filter ? " on" : " off"}`);
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
      stats.push(`${phase.encoder || "h264_nvenc"} · Q ${phase.quality || phase.crf || 25} · ${phase.preset || "p5"}`);
      if (phase.decoder && phase.decoder !== "default") stats.push(`解码 ${phase.hwaccel ? `${phase.hwaccel}/${phase.decoder}` : phase.decoder}`);
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
    revealNewNode("phases", key, card, root.children.length - 1);
  });

  renderChunkPanel(phaseStatus?.translation);
}

function getProjectFile(project, name) {
  return [...(project?.files || []), ...(project?.internal_files || [])].find((file) => file.name === name) || null;
}

function findProjectFile(project, predicate) {
  return [...(project?.files || []), ...(project?.internal_files || [])].find((file) => predicate(file.name || "", file)) || null;
}

function isFinalAssFileName(name) {
  const normalized = String(name || "").toLowerCase();
  if (!normalized.endsWith(".ass")) return false;
  if (normalized.includes("safe") || normalized.includes("segmentation_preview")) return false;
  return (
    normalized.startsWith("00_ass_") ||
    normalized.startsWith("08_bilingual_") ||
    normalized.startsWith("08_subtitle_") ||
    normalized.startsWith("08_source_")
  );
}

function renderLegacyProjectHealthSummary() {
  const root = el("projectHealthSummary");
  if (!root) return;
  const project = state.selectedProject;
  if (!project) {
    root.innerHTML = `
      <div class="local-feedback-head">
        <div>
          <h4>项目健康摘要</h4>
          <p>选择一个输出项目后展示 QA、实体和反馈采集状态。</p>
        </div>
      </div>
    `;
    return;
  }

  const segSummary = state.segmentationArtifacts.projectPath === project.path ? state.segmentationArtifacts.metrics?.summary || {} : {};
  const entitySummary = state.entityArtifacts.projectPath === project.path ? state.entityArtifacts.metrics?.summary || {} : {};
  const health = project.health || {};
  const blockingCount = Math.max(
    Number(health.qa_blocking_count ?? 0),
    Number(segSummary.blocking_issue_count ?? 0) + Number(segSummary.english_residue_blocking_count ?? 0),
  );
  const warningCount = Math.max(
    Number(health.qa_warning_count ?? 0),
    Number(segSummary.warning_count ?? 0) + Number(segSummary.english_residue_review_count ?? 0),
  );
  const entityIssueCount =
    Number(entitySummary.ass_issue_count ?? 0) +
    Number(entitySummary.target_entity_residue_count ?? 0) +
    Number(entitySummary.english_residue_count ?? 0);
  const hasFeedback = Boolean(getProjectFile(project, "00_style_examples.jsonl"));
  root.innerHTML = `
    <div class="local-feedback-head">
      <div>
        <h4>项目健康摘要</h4>
        <p>${escapeHtml(project.name)}</p>
      </div>
      <span class="entity-chip ${hasFeedback ? "" : "muted"}">ASS 反馈${hasFeedback ? "已采集" : "未采集"}</span>
    </div>
    <div class="feedback-summary-grid">
      <div class="entity-metric"><span>QA Blocking</span><strong>${escapeHtml(blockingCount)}</strong></div>
      <div class="entity-metric"><span>Warnings</span><strong>${escapeHtml(warningCount)}</strong></div>
      <div class="entity-metric"><span>实体问题</span><strong>${escapeHtml(entityIssueCount)}</strong></div>
      <div class="entity-metric"><span>ASS 反馈</span><strong>${hasFeedback ? "有" : "无"}</strong></div>
    </div>
    ${renderProjectHealthBadges(project)}
  `;
}

function renderProjectHealthBadges(project) {
  const health = project?.health || {};
  const badges = [
    ["05 translated", Boolean(getProjectFile(project, "05_translated_segments.json"))],
    ["ASS", Boolean(findProjectFile(project, isFinalAssFileName))],
    ["09 video", Boolean(findProjectFile(project, (name) => /^09_.*\.mp4$/i.test(name)))],
    ["QA", Boolean(getProjectFile(project, "07g_final_ass_qa.json") || getProjectFile(project, "07_qa_report.json") || getProjectFile(project, "07j_segmentation_qa_metrics.json"))],
    ["feedback", Boolean(getProjectFile(project, "00_style_examples.jsonl"))],
    [`health ${health.score ?? 0}`, Boolean(health.ready)],
  ];
  return `<div class="project-badges">${badges
    .map(([label, ok]) => `<span class="project-badge ${ok ? "ok" : "muted"}">${escapeHtml(label)}</span>`)
    .join("")}</div>`;
}

function renderReleaseArtifacts(project) {
  const artifacts = Array.isArray(project?.release_artifacts) ? project.release_artifacts : [];
  if (!artifacts.length) return `<div class="entity-empty">暂无发布必需品清单</div>`;
  return `<div class="project-release-list">${artifacts
    .map((artifact) => {
      const present = Boolean(artifact.present);
      return `<div class="project-release-item ${present ? "ok" : "missing"}">
        <span>${escapeHtml(artifact.label || artifact.key || "")}</span>
        <strong>${escapeHtml(artifact.name || "缺失")}</strong>
      </div>`;
    })
    .join("")}</div>`;
}

async function previewSelectedProjectArtifacts(projectPath) {
  if (!projectPath) return;
  const button = el("organizeProjectArtifactsBtn");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/api/organize-project-artifacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath, preview_only: true }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "预览整理方案失败");
    state.organizePreview = payload;
    renderProjectHealthSummary();
    showToast(`整理预览已生成：计划移动 ${payload.move_count || 0} 个内部文件`);
  } catch (error) {
    showToast(`整理预览失败：${error.message || error}`, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function confirmSelectedProjectArtifacts(projectPath) {
  if (!projectPath) return;
  const button = el("confirmOrganizeProjectArtifactsBtn");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/api/organize-project-artifacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "确认整理项目产物失败");
    if (Array.isArray(payload.projects)) {
      state.projects = payload.projects;
      state.selectedProject = payload.projects.find((project) => project.path === projectPath) || payload.project || state.selectedProject;
      renderProjects(state.projects);
    }
    state.organizePreview = null;
    renderProjectHealthSummary();
    showToast(`发布产物已整理：移动 ${payload.moved_count || 0} 个内部文件`);
  } catch (error) {
    showToast(`发布产物整理失败：${error.message || error}`, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

function renderOrganizePreview(project) {
  const preview = state.organizePreview;
  if (!preview || preview.project_path !== project?.path) return "";
  const planned = Array.isArray(preview.planned) ? preview.planned : [];
  const kept = Array.isArray(preview.kept) ? preview.kept : [];
  const previewRows = planned.slice(0, 10);
  return `
    <div class="organize-preview">
      <div class="project-health-section-head">
        <strong>整理预览</strong>
        <button id="confirmOrganizeProjectArtifactsBtn" class="mini-btn" type="button">确认移动内部文件</button>
      </div>
      <p class="local-feedback-note">安全两段式：这里还没有移动文件；确认后才会把非发布必需品移入 99_internal_artifacts。</p>
      ${
        previewRows.length
          ? `<div class="organize-preview-list">${previewRows
              .map((item) => `<div><span>${escapeHtml(item.from || "")}</span><strong>${escapeHtml(item.to || "")}</strong></div>`)
              .join("")}</div>`
          : `<div class="entity-empty">没有需要移动的内部文件。</div>`
      }
      ${
        planned.length > previewRows.length
          ? `<p class="local-feedback-note">还有 ${escapeHtml(planned.length - previewRows.length)} 个移动项未展开显示。</p>`
          : ""
      }
      <p class="local-feedback-note">将保留 ${escapeHtml(kept.length)} 个发布必需品在项目根目录。</p>
    </div>
  `;
}

function renderProjectHealthSummary() {
  const root = el("projectHealthSummary");
  if (!root) return;
  const project = state.selectedProject;
  if (!project) {
    root.innerHTML = `
      <div class="local-feedback-head">
        <div>
          <h4>项目健康摘要</h4>
          <p>选择一个输出项目后展示 QA、实体、反馈采集和发布必需品状态。</p>
        </div>
      </div>
    `;
    return;
  }

  const segSummary = state.segmentationArtifacts.projectPath === project.path ? state.segmentationArtifacts.metrics?.summary || {} : {};
  const entitySummary = state.entityArtifacts.projectPath === project.path ? state.entityArtifacts.metrics?.summary || {} : {};
  const blockingCount = Number(segSummary.blocking_issue_count ?? 0) + Number(segSummary.english_residue_blocking_count ?? 0);
  const warningCount = Number(segSummary.warning_count ?? 0) + Number(segSummary.english_residue_review_count ?? 0);
  const entityIssueCount =
    Number(entitySummary.ass_issue_count ?? 0) +
    Number(entitySummary.target_entity_residue_count ?? 0) +
    Number(entitySummary.english_residue_count ?? 0);
  const health = project.health || {};
  const hasFeedback = Boolean(getProjectFile(project, "00_style_examples.jsonl"));
  const missing = Array.isArray(health.missing_release_artifacts) ? health.missing_release_artifacts : [];
  const healthLabel = health.ready ? "可发布" : missing.length ? `缺少 ${missing.join(" / ")}` : "待复核";
  root.innerHTML = `
    <div class="local-feedback-head">
      <div>
        <h4>项目健康摘要</h4>
        <p>${escapeHtml(project.name)} · ${escapeHtml(healthLabel)}</p>
      </div>
      <span class="entity-chip ${health.ready ? "" : "muted"}">Health ${escapeHtml(health.score ?? 0)}</span>
    </div>
    <div class="feedback-summary-grid">
      <div class="entity-metric"><span>发布必需品</span><strong>${escapeHtml(`${health.release_artifact_count ?? 0}/${health.release_artifact_total ?? 5}`)}</strong></div>
      <div class="entity-metric"><span>QA Blocking</span><strong>${escapeHtml(blockingCount)}</strong></div>
      <div class="entity-metric"><span>Warnings</span><strong>${escapeHtml(warningCount)}</strong></div>
      <div class="entity-metric"><span>实体问题</span><strong>${escapeHtml(entityIssueCount)}</strong></div>
      <div class="entity-metric"><span>ASS 反馈</span><strong>${hasFeedback ? "有" : "无"}</strong></div>
      <div class="entity-metric"><span>内部文件</span><strong>${escapeHtml(health.internal_file_count ?? 0)}</strong></div>
    </div>
    <div class="project-health-section">
      <div class="project-health-section-head">
        <strong>发布必需品</strong>
        <button id="organizeProjectArtifactsBtn" class="mini-btn" type="button">预览整理方案</button>
      </div>
      ${renderReleaseArtifacts(project)}
      <p class="local-feedback-note">保留简介、两个封面、最终 ASS 和烤制视频；其他根目录文件移动到 99_internal_artifacts。</p>
    </div>
    ${renderOrganizePreview(project)}
    ${renderProjectHealthBadges(project)}
  `;
  el("organizeProjectArtifactsBtn")?.addEventListener("click", () => previewSelectedProjectArtifacts(project.path));
  el("confirmOrganizeProjectArtifactsBtn")?.addEventListener("click", () => confirmSelectedProjectArtifacts(project.path));
}

const ENTITY_ARTIFACT_FILES = {
  metrics: "07i_entity_metrics.json",
  review: "06f_entity_review.tsv",
  qa: "07h_entity_qa.tsv",
  residue: "07k_english_residue_review.tsv",
  residueReport: "07k_english_residue_report.json",
  normalized: "06g_entity_normalized_segments.json",
  decisions: "00_entity_decisions.json",
};

const SEGMENTATION_ARTIFACT_FILES = {
  metrics: "07j_segmentation_qa_metrics.json",
  residue: "07k_english_residue_report.json",
  residueTsv: "07k_english_residue_review.tsv",
  allocation: "05a_semantic_allocation_report.json",
  repair: "03b_source_repair_report.json",
  previewMetrics: "segmentation_preview_metrics.json",
};

function projectEntitySignature(project) {
  return Object.values(ENTITY_ARTIFACT_FILES)
    .map((name) => {
      const file = getProjectFile(project, name);
      return `${name}:${file?.mtime_ts || 0}:${file?.size || 0}`;
    })
    .join("|");
}

function projectSegmentationSignature(project) {
  return Object.values(SEGMENTATION_ARTIFACT_FILES)
    .map((name) => {
      const file = getProjectFile(project, name);
      return `${name}:${file?.mtime_ts || 0}:${file?.size || 0}`;
    })
    .join("|");
}

function parseTsv(content) {
  const lines = String(content || "").replace(/^\uFEFF/, "").split(/\r?\n/).filter((line) => line.length);
  if (!lines.length) return [];
  const headers = lines[0].split("\t");
  return lines.slice(1).map((line) => {
    const values = line.split("\t");
    return headers.reduce((row, header, index) => {
      row[header] = values[index] ?? "";
      return row;
    }, {});
  });
}

async function fetchOutputFileContent(file) {
  if (!file?.path) return "";
  const response = await fetch(`/api/file?path=${encodeURIComponent(file.path)}`);
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error || `${file.name} failed to load`);
  }
  return payload.content || "";
}

async function fetchJsonArtifact(file) {
  const content = await fetchOutputFileContent(file);
  return JSON.parse(content || "{}");
}

async function fetchTsvArtifact(file) {
  return parseTsv(await fetchOutputFileContent(file));
}

function countRows(rows) {
  return Array.isArray(rows) ? rows.length : 0;
}

function renderMetricCards(summary) {
  const metrics = [
    ["决策数", summary?.entity_decision_count ?? 0],
    ["改动分段", summary?.segments_changed ?? 0],
    ["参考文本修正", summary?.reference_text_replacements ?? 0],
    ["译文修正", summary?.target_text_replacements ?? 0],
    ["ASS 问题", summary?.ass_issue_count ?? 0],
    ["译文残留实体", summary?.target_entity_residue_count ?? 0],
    ["英文残留", summary?.english_residue_count ?? 0],
    ["残留复核", summary?.english_residue_review_count ?? 0],
  ];
  return metrics
    .map(
      ([label, value]) => `
        <div class="entity-metric">
          <span>${label}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `
    )
    .join("");
}

function renderEntityTypeCounts(metrics) {
  const counts = metrics?.entity_type_counts || {};
  const entries = Object.entries(counts).filter(([, value]) => Number(value) > 0);
  if (!entries.length) return `<span class="entity-chip muted">暂无分类决策</span>`;
  return entries
    .map(([type, value]) => `<span class="entity-chip">${escapeHtml(type)} <strong>${escapeHtml(value)}</strong></span>`)
    .join("");
}

function renderEntityTable({ rows, columns, emptyText, limit = 8 }) {
  const visibleRows = (rows || []).slice(0, limit);
  if (!visibleRows.length) {
    return `<div class="entity-empty">${escapeHtml(emptyText)}</div>`;
  }
  return `
    <div class="entity-table-wrap">
      <table class="entity-table">
        <thead>
          <tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${visibleRows
            .map(
              (row) => `
                <tr>
                  ${columns.map((column) => `<td>${escapeHtml(row[column.key] || "")}</td>`).join("")}
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </div>
    ${(rows || []).length > visibleRows.length ? `<div class="entity-table-note">当前显示 ${visibleRows.length} / ${rows.length} 行；打开 TSV 可查看完整审阅列表。</div>` : ""}
  `;
}

function referenceRowsFromSegments(segments) {
  return (segments || [])
    .filter((segment) => segment && typeof segment === "object")
    .filter((segment) => segment.reference_text || segment.source_text || segment.target_text)
    .map((segment) => ({
      segment_id: segment.id ?? "",
      source_text: segment.source_text || "",
      reference_text: segment.reference_text || "[使用 source_text]",
      target_text: segment.target_text || "",
    }));
}

function renderEntityReviewPanel() {
  const panel = el("entityReviewPanel");
  if (!panel) return;
  const project = state.selectedProject;
  const artifacts = state.entityArtifacts;
  const bootstrapMode = normalizeBootstrapMode(state.config?.bootstrap_entity_decisions);

  if (!project) {
    panel.innerHTML = `
      <div class="entity-panel-head">
        <div>
          <h4>实体审阅</h4>
          <p>选择一个项目后，可查看实体指标、审阅行、QA 行和标准化参考文本。</p>
        </div>
      </div>
    `;
    renderProjectHealthSummary();
    return;
  }

  if (artifacts.loading && artifacts.projectPath === project.path) {
    panel.innerHTML = `
      <div class="entity-panel-head">
        <div>
          <h4>实体审阅</h4>
          <p>正在从 ${escapeHtml(project.name)} 读取实体产物。</p>
        </div>
      </div>
      <div class="entity-loading">正在读取项目产物...</div>
    `;
    renderProjectHealthSummary();
    return;
  }

  const summary = artifacts.metrics?.summary || {};
  const missing = artifacts.missing || [];
  const errors = artifacts.errors || [];
  const decisions = artifacts.decisions;
  const decisionEntities = Array.isArray(decisions?.entities) ? decisions.entities.length : 0;
  const decisionsState = getProjectFile(project, "00_entity_decisions.json")
    ? `${decisionEntities} 条项目决策`
    : "无项目决策文件";
  const referenceRows = referenceRowsFromSegments(artifacts.normalizedSegments);

  panel.innerHTML = `
    <div class="entity-panel-head">
      <div>
        <h4>实体审阅</h4>
        <p>选中项目：${escapeHtml(project.name)}</p>
      </div>
      <div class="entity-status-stack">
        <span class="entity-status">实体决策引导：${escapeHtml(bootstrapMode)}</span>
        <span class="entity-status ${getProjectFile(project, "00_entity_decisions.json") ? "ok" : "muted"}">${escapeHtml(decisionsState)}</span>
      </div>
    </div>

    <div class="entity-metrics-grid">
      ${artifacts.metrics ? renderMetricCards(summary) : `<div class="entity-empty wide">07i_entity_metrics.json 暂未生成。</div>`}
    </div>

    <div class="entity-type-row">
      ${renderEntityTypeCounts(artifacts.metrics)}
    </div>

    ${
      missing.length || errors.length
        ? `<div class="entity-alert">${[...missing.map((name) => `${name} 缺失`), ...errors].map(escapeHtml).join(" · ")}</div>`
        : ""
    }

    <div class="entity-sections">
      <section class="entity-section">
        <div class="entity-section-head">
          <h5>实体审阅 TSV</h5>
          <span>${countRows(artifacts.reviewRows)} 行</span>
        </div>
        ${renderEntityTable({
          rows: artifacts.reviewRows,
          columns: [
            { key: "segment_id", label: "分段" },
            { key: "candidate", label: "候选实体" },
            { key: "entity_type", label: "类型" },
            { key: "reference_text", label: "参考文本" },
            { key: "target_text", label: "译文" },
            { key: "reason", label: "原因" },
          ],
          emptyText: "06f_entity_review.tsv 中未找到实体审阅行。",
        })}
      </section>

      <section class="entity-section">
        <div class="entity-section-head">
          <h5>实体 QA TSV</h5>
          <span>${countRows(artifacts.qaRows)} 行</span>
        </div>
        ${renderEntityTable({
          rows: artifacts.qaRows,
          columns: [
            { key: "issue_type", label: "问题" },
            { key: "segment_id", label: "分段" },
            { key: "entity_type", label: "类型" },
            { key: "layer", label: "层" },
            { key: "text", label: "文本" },
            { key: "line_text", label: "行文本" },
          ],
          emptyText: "07h_entity_qa.tsv 中未找到实体 QA 行。",
        })}
      </section>

      <section class="entity-section wide">
        <div class="entity-section-head">
          <h5>英文残留评分 TSV</h5>
          <span>${countRows(artifacts.residueRows)} 行</span>
        </div>
        ${renderEntityTable({
          rows: artifacts.residueRows,
          columns: [
            { key: "segment_id", label: "分段" },
            { key: "candidate", label: "残留" },
            { key: "preserve_score", label: "分数" },
            { key: "decision", label: "决策" },
            { key: "reason_codes", label: "原因" },
            { key: "target_text", label: "译文" },
          ],
          emptyText: "07k_english_residue_review.tsv 中未找到英文残留行。",
          limit: 10,
        })}
      </section>

      <section class="entity-section wide">
        <div class="entity-section-head">
          <h5>参考文本对照</h5>
          <span>${referenceRows.length} 段</span>
        </div>
        ${renderEntityTable({
          rows: referenceRows,
          columns: [
            { key: "segment_id", label: "分段" },
            { key: "source_text", label: "原始源文本" },
            { key: "reference_text", label: "标准化参考文本" },
            { key: "target_text", label: "译文" },
          ],
          emptyText: "06g_entity_normalized_segments.json 中未找到 reference_text 行。",
          limit: 6,
        })}
      </section>
    </div>
  `;
  renderProjectHealthSummary();
}

function renderSegmentationMetricCards(metrics) {
  const summary = metrics?.summary || {};
  const segmentation = metrics?.segmentation || {};
  const allocation = metrics?.allocation || {};
  const repair = metrics?.source_repair || {};
  const display = metrics?.display_grouping || {};
  const residue = metrics?.english_residue || {};
  const cards = [
    ["短残片", segmentation.short_fragment_count ?? 0],
    ["混句", segmentation.mixed_sentence_count ?? 0],
    ["孤立句尾词", segmentation.orphan_terminal_tail_count ?? 0],
    ["独立语气词", segmentation.standalone_discourse_particle_count ?? 0],
    ["歧义语气词", segmentation.ambiguous_discourse_tail_count ?? 0],
    ["function 边界", segmentation.function_edge_count ?? 0],
    ["语义分配复核", allocation.review_count ?? 0],
    ["ASR 候选", repair.candidate_count ?? 0],
    ["ASR 复核", repair.review_count ?? 0],
    ["短句合屏", display.group_count ?? 0],
    ["英文残留", residue.english_residue_blocking_count ?? summary.english_residue_blocking_count ?? 0],
    ["残留复核", residue.english_residue_review_count ?? summary.english_residue_review_count ?? 0],
  ];
  return cards
    .map(
      ([label, value]) => `
        <div class="entity-metric">
          <span>${label}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `
    )
    .join("");
}

function segmentationRowsFromMetrics(metrics) {
  const segmentation = metrics?.segmentation || {};
  const rows = [];
  for (const sample of segmentation.short_fragment_samples || []) {
    rows.push({
      issue_type: "short_fragment",
      segment_id: sample.segment_id || "",
      text: sample.text || "",
    });
  }
  for (const sample of segmentation.mixed_sentence_samples || []) {
    rows.push({
      issue_type: "mixed_sentence",
      segment_id: sample.segment_id || "",
      text: sample.source_text || sample.target_text || "",
    });
  }
  for (const sample of segmentation.function_edge_samples || []) {
    rows.push({
      issue_type: "function_edge",
      segment_id: sample.segment_id || "",
      text: sample.source_text || "",
    });
  }
  for (const sample of segmentation.orphan_terminal_tail_samples || []) {
    rows.push({
      issue_type: "orphan_terminal_tail",
      segment_id: sample.segment_id || "",
      text: `${sample.previous_text || ""} → ${sample.source_text || ""}`,
    });
  }
  for (const sample of segmentation.standalone_discourse_particle_samples || []) {
    rows.push({
      issue_type: "standalone_discourse_particle",
      segment_id: sample.segment_id || "",
      text: `${sample.previous_text || ""} → ${sample.source_text || ""}`,
    });
  }
  for (const sample of segmentation.ambiguous_discourse_tail_samples || []) {
    rows.push({
      issue_type: "ambiguous_discourse_tail",
      segment_id: sample.segment_id || "",
      text: `${sample.previous_text || ""} → ${sample.source_text || ""}`,
    });
  }
  for (const sample of segmentation.too_short_samples || []) {
    rows.push({
      issue_type: "too_short",
      segment_id: sample.segment_id || "",
      text: sample.text || "",
    });
  }
  for (const sample of segmentation.too_long_samples || []) {
    rows.push({
      issue_type: "too_long",
      segment_id: sample.segment_id || "",
      text: sample.text || "",
    });
  }
  return rows;
}

function renderSegmentationReviewPanel() {
  const panel = el("segmentationReviewPanel");
  if (!panel) return;
  const project = state.selectedProject;
  const artifacts = state.segmentationArtifacts;
  if (!project) {
    panel.innerHTML = `
      <div class="entity-panel-head">
        <div>
          <h4>字幕 QA</h4>
          <p>选择一个项目后，可查看短残片、混句、语义分配和 ASR 修复统计。</p>
        </div>
      </div>
    `;
    return;
  }
  if (artifacts.loading && artifacts.projectPath === project.path) {
    panel.innerHTML = `
      <div class="entity-panel-head">
        <div>
          <h4>字幕 QA</h4>
          <p>正在从 ${escapeHtml(project.name)} 读取字幕 QA 产物。</p>
        </div>
      </div>
      <div class="entity-loading">正在读取 QA 产物...</div>
    `;
    return;
  }
  const metrics = artifacts.metrics || {};
  const rows = segmentationRowsFromMetrics(metrics);
  panel.innerHTML = `
    <div class="entity-panel-head">
      <div>
        <h4>字幕 QA</h4>
        <p>项目：${escapeHtml(project.name)}</p>
      </div>
      <div class="entity-status-stack">
        <span class="entity-status ${getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.metrics) ? "ok" : "muted"}">${escapeHtml(getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.metrics) ? "07j 已生成" : "暂无 07j")}</span>
        <span class="entity-status ${getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.allocation) ? "ok" : "muted"}">${escapeHtml(getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.allocation) ? "05a 语义分配" : "暂无分配报告")}</span>
      </div>
    </div>
    <div class="entity-metrics-grid">
      ${artifacts.metrics ? renderSegmentationMetricCards(metrics) : `<div class="entity-empty wide">07j_segmentation_qa_metrics.json 暂未生成。</div>`}
    </div>
    <div class="entity-type-row">
      <span class="entity-chip">blocking <strong>${escapeHtml(metrics.summary?.blocking_issue_count ?? 0)}</strong></span>
      <span class="entity-chip">warnings <strong>${escapeHtml(metrics.summary?.warning_issue_count ?? 0)}</strong></span>
      <span class="entity-chip">pass <strong>${escapeHtml(metrics.summary?.pass ? "yes" : "no")}</strong></span>
    </div>
    <div class="entity-sections">
      <section class="entity-section wide">
        <div class="entity-section-head">
          <h5>问题样例</h5>
          <span>${rows.length} 行</span>
        </div>
        ${renderEntityTable({
          rows,
          columns: [
            { key: "issue_type", label: "问题" },
            { key: "segment_id", label: "分段" },
            { key: "text", label: "文本" },
          ],
          emptyText: "当前项目没有可展示的字幕 QA 样例。",
          limit: 10,
        })}
      </section>
      <section class="entity-section wide">
        <div class="entity-section-head">
          <h5>产物入口</h5>
          <span>ASS / JSON</span>
        </div>
        <div class="qa-artifact-links">
          ${[
            SEGMENTATION_ARTIFACT_FILES.metrics,
            SEGMENTATION_ARTIFACT_FILES.residue,
            SEGMENTATION_ARTIFACT_FILES.residueTsv,
            SEGMENTATION_ARTIFACT_FILES.allocation,
            SEGMENTATION_ARTIFACT_FILES.repair,
            "00_ASS_bilingual_zh_en.ass",
            "08_bilingual_zh_en.segmentation_preview.ass",
            "segmentation_preview_metrics.json",
          ]
            .map((name) => {
              const file = name === "00_ASS_bilingual_zh_en.ass" ? findProjectFile(project, isFinalAssFileName) : getProjectFile(project, name);
              if (!file) return `<span class="entity-chip muted">${escapeHtml(name)}</span>`;
              const label = name === "00_ASS_bilingual_zh_en.ass" ? file.name : name;
              return `<button class="entity-chip qa-link" data-file-path="${escapeHtml(file.path)}" data-file-name="${escapeHtml(file.name)}" type="button">${escapeHtml(label)}</button>`;
            })
            .join("")}
        </div>
      </section>
    </div>
  `;
  panel.querySelectorAll(".qa-link").forEach((button) => {
    button.addEventListener("click", () => {
      const path = button.getAttribute("data-file-path");
      const name = button.getAttribute("data-file-name");
      if (path && name) openFile(path, name);
    });
  });
}

async function loadSegmentationArtifactsForProject(project) {
  const token = state.segmentationArtifacts.token + 1;
  const files = {
    metrics: getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.metrics),
    residue: getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.residue),
    allocation: getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.allocation),
    repair: getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.repair),
    previewMetrics: getProjectFile(project, SEGMENTATION_ARTIFACT_FILES.previewMetrics),
  };
  state.segmentationArtifacts = {
    projectPath: project?.path || null,
    signature: projectSegmentationSignature(project),
    token,
    loading: true,
    metrics: null,
    allocation: null,
    repair: null,
    missing: Object.entries(files).filter(([, file]) => !file).map(([name]) => SEGMENTATION_ARTIFACT_FILES[name]),
    errors: [],
  };
  renderSegmentationReviewPanel();
  const nextArtifacts = { ...state.segmentationArtifacts, loading: false, errors: [] };
  const guarded = async (key, loader) => {
    if (!files[key]) return null;
    try {
      return await loader(files[key]);
    } catch (error) {
      nextArtifacts.errors.push(`${files[key].name}: ${error.message || error}`);
      return null;
    }
  };
  const [metrics, residue, allocation, repair] = await Promise.all([
    guarded("metrics", fetchJsonArtifact),
    guarded("residue", fetchJsonArtifact),
    guarded("allocation", fetchJsonArtifact),
    guarded("repair", fetchJsonArtifact),
  ]);
  if (state.segmentationArtifacts.token !== token) return;
  nextArtifacts.metrics = metrics || allocation || repair || null;
  if (residue?.summary) {
    nextArtifacts.metrics = {
      ...(nextArtifacts.metrics || {}),
      english_residue: residue.summary,
      summary: {
        ...((nextArtifacts.metrics || {}).summary || {}),
        english_residue_blocking_count: residue.summary.english_residue_blocking_count ?? 0,
        english_residue_review_count: residue.summary.english_residue_review_count ?? 0,
        english_residue_preserved_count: residue.summary.english_residue_preserved_count ?? 0,
      },
    };
  }
  nextArtifacts.allocation = allocation || null;
  nextArtifacts.repair = repair || null;
  nextArtifacts.signature = projectSegmentationSignature(project);
  state.segmentationArtifacts = nextArtifacts;
  renderSegmentationReviewPanel();
}

function refreshSegmentationArtifactsForSelectedProject() {
  const project = state.selectedProject;
  if (!project) {
    state.segmentationArtifacts = {
      projectPath: null,
      signature: "",
      token: state.segmentationArtifacts.token + 1,
      loading: false,
      metrics: null,
      allocation: null,
      repair: null,
      missing: [],
      errors: [],
    };
    renderSegmentationReviewPanel();
    renderProjectHealthSummary();
    return;
  }
  const signature = projectSegmentationSignature(project);
  if (state.segmentationArtifacts.projectPath === project.path && state.segmentationArtifacts.signature === signature) {
    renderSegmentationReviewPanel();
    renderProjectHealthSummary();
    return;
  }
  loadSegmentationArtifactsForProject(project);
}

async function loadEntityArtifactsForProject(project) {
  const token = state.entityArtifacts.token + 1;
  const files = {
    metrics: getProjectFile(project, ENTITY_ARTIFACT_FILES.metrics),
    review: getProjectFile(project, ENTITY_ARTIFACT_FILES.review),
    qa: getProjectFile(project, ENTITY_ARTIFACT_FILES.qa),
    residue: getProjectFile(project, ENTITY_ARTIFACT_FILES.residue),
    residueReport: getProjectFile(project, ENTITY_ARTIFACT_FILES.residueReport),
    normalized: getProjectFile(project, ENTITY_ARTIFACT_FILES.normalized),
    decisions: getProjectFile(project, ENTITY_ARTIFACT_FILES.decisions),
  };
  state.entityArtifacts = {
    projectPath: project?.path || null,
    signature: projectEntitySignature(project),
    token,
    loading: true,
    metrics: null,
    reviewRows: [],
    qaRows: [],
    residueRows: [],
    normalizedSegments: [],
    decisions: null,
    missing: Object.entries(files).filter(([, file]) => !file).map(([name]) => ENTITY_ARTIFACT_FILES[name]),
    errors: [],
  };
  renderEntityReviewPanel();

  const nextArtifacts = { ...state.entityArtifacts, loading: false, errors: [] };
  const guarded = async (key, loader) => {
    if (!files[key]) return;
    try {
      return await loader(files[key]);
    } catch (error) {
      nextArtifacts.errors.push(`${files[key].name}: ${error.message || error}`);
      return null;
    }
  };

  const [metrics, reviewRows, qaRows, residueRows, residueReport, normalized, decisions] = await Promise.all([
    guarded("metrics", fetchJsonArtifact),
    guarded("review", fetchTsvArtifact),
    guarded("qa", fetchTsvArtifact),
    guarded("residue", fetchTsvArtifact),
    guarded("residueReport", fetchJsonArtifact),
    guarded("normalized", fetchJsonArtifact),
    guarded("decisions", fetchJsonArtifact),
  ]);

  if (state.entityArtifacts.token !== token) return;
  nextArtifacts.metrics = metrics || null;
  if (!nextArtifacts.metrics && residueReport) nextArtifacts.metrics = { summary: residueReport.summary || {} };
  if (nextArtifacts.metrics && residueReport?.summary) {
    nextArtifacts.metrics = {
      ...nextArtifacts.metrics,
      summary: {
        ...(nextArtifacts.metrics.summary || {}),
        english_residue_count: residueReport.summary.english_residue_blocking_count ?? 0,
        english_residue_review_count: residueReport.summary.english_residue_review_count ?? 0,
        english_residue_preserved_count: residueReport.summary.english_residue_preserved_count ?? 0,
      },
    };
  }
  nextArtifacts.reviewRows = reviewRows || [];
  nextArtifacts.qaRows = qaRows || [];
  nextArtifacts.residueRows = residueRows || [];
  nextArtifacts.normalizedSegments = Array.isArray(normalized?.segments) ? normalized.segments : [];
  nextArtifacts.decisions = decisions || null;
  nextArtifacts.signature = projectEntitySignature(project);
  state.entityArtifacts = nextArtifacts;
  renderEntityReviewPanel();
}

function refreshEntityArtifactsForSelectedProject() {
  const project = state.selectedProject;
  if (!project) {
    state.entityArtifacts = {
      projectPath: null,
      signature: "",
      token: state.entityArtifacts.token + 1,
      loading: false,
      metrics: null,
      reviewRows: [],
      qaRows: [],
      residueRows: [],
      normalizedSegments: [],
      decisions: null,
      missing: [],
      errors: [],
    };
    renderEntityReviewPanel();
    renderProjectHealthSummary();
    return;
  }
  const signature = projectEntitySignature(project);
  if (state.entityArtifacts.projectPath === project.path && state.entityArtifacts.signature === signature) {
    renderEntityReviewPanel();
    renderProjectHealthSummary();
    return;
  }
  loadEntityArtifactsForProject(project);
}

function openFile(path, name) {
  state.selectedFilePath = path;
  const matchedProject = state.projects.find((project) => project.files.some((file) => file.path === path)) || null;
  state.selectedProject = matchedProject;
  state.selectedFileProjectPath = matchedProject?.path || null;
  el("previewTitle").textContent = name;
  const video = el("videoPreview");
  const text = el("textPreview");
  updateFileActionButtons();

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
    state.selectedFileProjectPath = null;
    if (!state.selectedFilePath) {
      el("previewTitle").textContent = "文件预览";
      el("textPreview").textContent = "";
      el("videoPreview").classList.add("hidden");
      el("videoPreview").src = "";
      updateFileActionButtons();
    }
    return;
  }
  const preferredPath = state.selectedFileProjectPath || state.selectedProject?.path;
  const matched = projects.find((project) => project.path === preferredPath);
  state.selectedProject = matched || projects[0];
  if (!projects.some((project) => project.path === state.expandedProjectPath)) {
    state.expandedProjectPath = state.selectedProject?.path || null;
  }
}

function renderProjects(projects) {
  state.projects = projects;
  syncSelectedProject(projects);
  refreshSegmentationArtifactsForSelectedProject();
  refreshEntityArtifactsForSelectedProject();
  const list = el("projectList");
  list.innerHTML = "";

  projects.forEach((project) => {
    const wrapper = document.createElement("div");
    const expanded = state.expandedProjectPath === project.path;
    wrapper.className =
      "project-item" +
      (state.selectedProject?.path === project.path ? " active" : "") +
      (expanded ? " expanded" : " collapsed");
    wrapper.innerHTML = `
      <div><strong>${project.name}</strong></div>
      <div class="meta-row"><span>${project.files.length} files</span><span>${expanded ? "收起" : "展开"}</span></div>
      ${renderProjectHealthBadges(project)}
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
        state.expandedProjectPath = project.path;
        openFile(file.path, file.name);
        renderProjects(state.projects);
      });
      fileList.appendChild(fileNode);
    });

    wrapper.addEventListener("click", () => {
      state.selectedProject = project;
      state.selectedFileProjectPath = project.path;
      state.expandedProjectPath = project.path;
      renderProjectHealthSummary();
      refreshEntityArtifactsForSelectedProject();
      renderProjects(state.projects);
      renderLocalFeedbackSummary(state.localFeedbackSummary);
      scrollToWorkspaceDetails();
    });

    if (expanded) wrapper.appendChild(fileList);
    list.appendChild(wrapper);
    revealNewNode("projects", project.path || project.name, wrapper, list.children.length - 1);
  });

  if (!projects.length) {
    list.innerHTML = `<div class="stage-item empty-card"><strong>暂无输出项目</strong><div class="meta-row"><span>运行流程后，项目产物会显示在这里。</span></div></div>`;
    revealChildren(list, ".stage-item");
  }
  renderProjectHealthSummary();
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
  const modeLabel = proxy.mode === "proxy" ? "代理模式" : "直连模式";
  card.innerHTML = `
    <div class="proxy-status-head">
      <strong>${proxy.ok ? "网络检测通过" : "网络检测失败"}</strong>
      <span>${proxy.checked_at || ""}</span>
    </div>
    <div class="proxy-status-meta">${modeLabel}：${proxy.proxy_url || "未设置，直接访问 YouTube"}</div>
    <div class="proxy-status-list">
      ${(proxy.results || [])
        .map((item) => {
          const detail = item.ok ? `状态 ${item.status_code}` : safeText(item.error || item.raw_error || "连接失败");
          return `<div class="proxy-status-row"><span>${item.name}</span><strong>${detail}</strong></div>`;
        })
        .join("")}
    </div>
  `;
  revealNewNode("statusCards", `proxy:${proxy.ok}:${proxy.checked_at || ""}`, card);
}

function renderIdmStatus() {
  const card = el("idmStatusCard");
  const idm = state.idmStatus;
  if (!idm) {
    card.classList.add("hidden");
    card.innerHTML = "";
    return;
  }

  card.className = `proxy-status-card ${idm.ok ? "proxy-ok" : "proxy-bad"}`;
  card.innerHTML = `
    <div class="proxy-status-head">
      <strong>${idm.ok ? "IDM 已就绪" : "IDM 未就绪"}</strong>
      <span>${idm.output_dir_writable ? "目录可写" : "目录不可写"}</span>
    </div>
    <div class="proxy-status-meta">程序：${idm.resolved_path || idm.configured_path || "未找到"}</div>
    <div class="proxy-status-list">
      <div class="proxy-status-row"><span>输出目录</span><strong>${idm.output_dir || ""}</strong></div>
      <div class="proxy-status-row"><span>目录存在</span><strong>${idm.output_dir_exists ? "是" : "否"}</strong></div>
    </div>
  `;
  revealNewNode("statusCards", `idm:${idm.ok}:${idm.resolved_path || idm.configured_path || ""}`, card);
}

function renderYoutubeMeta() {
  const card = el("youtubeMetaCard");
  const meta = state.youtubeMeta;
  const cover = el("youtubeCoverPreview");
  const info = el("youtubeInfoPreview");
  if (!meta) {
    card.classList.add("hidden");
    card.innerHTML = "";
    cover.classList.add("hidden");
    cover.removeAttribute("src");
    info.textContent = "";
    return;
  }

  if (meta.error) {
    card.className = "proxy-status-card proxy-bad";
    card.innerHTML = `
      <div class="proxy-status-head">
        <strong>YouTube 获取失败</strong>
        <span>${escapeHtml(meta.mode || "")}</span>
      </div>
      <div class="proxy-status-meta">${escapeHtml(meta.error)}</div>
    `;
    cover.classList.add("hidden");
    cover.removeAttribute("src");
    info.textContent = meta.error;
    revealNewNode("statusCards", `youtube:error:${meta.error || ""}`, card);
    return;
  }

  card.className = "proxy-status-card proxy-ok";
  card.innerHTML = `
    <div class="proxy-status-head">
      <strong>原视频信息</strong>
      <span>${meta.published_at || ""}</span>
    </div>
    <div class="proxy-status-list">
      <div class="proxy-status-row"><span>原作者</span><strong>${escapeHtml(meta.author || "")}</strong></div>
      <div class="proxy-status-row"><span>原发布时间</span><strong>${escapeHtml(meta.published_at || "")}</strong></div>
      <div class="proxy-status-row"><span>原视频标题</span><strong>${escapeHtml(meta.title || "")}</strong></div>
      <div class="proxy-status-row"><span>原视频简介</span><strong>${escapeHtml(meta.description || "")}</strong></div>
    </div>
  `;
  info.textContent = `原作者：【${meta.author || ""}】\n原发布时间：【${meta.published_at || ""}】\n原视频标题：【${meta.title || ""}】\n原视频简介：【${meta.description || ""}】\n`;
  if (meta.cover_path) {
    cover.src = `/output/${encodeURI(meta.cover_path.split("\\output\\").pop().replaceAll("\\", "/"))}`;
    cover.classList.remove("hidden");
  } else if (meta.cover_url) {
    cover.src = meta.cover_url;
    cover.classList.remove("hidden");
  }
  revealNewNode("statusCards", `youtube:ok:${meta.title || meta.cover_path || meta.cover_url || ""}`, card);
}

function bilibiliDecisionLabel(decision) {
  const labels = {
    high_confidence_possible_duplicate: "发现高置信候选",
    medium_confidence_review: "发现中置信候选",
    low_confidence_related: "仅发现低置信相关",
    no_clear_duplicate_found: "未发现明确重复",
    no_candidates_manual_review: "未解析到候选，可手动复核",
    no_candidates_search_completed: "已搜索，未发现可解析候选",
    search_unavailable_manual_review: "检测失败，可手动复核",
  };
  return labels[decision] || "未检测";
}

function bilibiliSearchStateLabel(searchState, decision) {
  const labels = {
    matched_candidates: bilibiliDecisionLabel(decision),
    searched_no_parseable_candidates: "已搜索，未发现可解析候选",
    search_unavailable: "搜索通道受限，可手动复核",
  };
  return labels[searchState] || bilibiliDecisionLabel(decision);
}

function renderBilibiliDuplicate() {
  const card = el("bilibiliDuplicateCard");
  const stateValue = state.bilibiliDuplicate;
  if (!card) return;
  if (!stateValue) {
    card.classList.add("hidden");
    card.innerHTML = "";
    return;
  }

  const status = stateValue.status || "idle";
  const report = stateValue.report || {};
  const decision = report.decision || "";
  const searchState = report.search_state || "";
  const candidates = Array.isArray(report.candidates) ? report.candidates.slice(0, 5) : [];
  const query = (report.queries || report.query_plan || [])[0] || {};
  const best = report.best_candidate || candidates[0] || null;
  const searchSummary = report.search_summary || {};
  const policy = stateValue.workflow_policy || report.workflow_policy || {};
  const policyText =
    policy.blocks_translation === false
      ? "独立复核：不阻塞下载、翻译、烤制或反馈学习"
      : "查重状态仅作复核参考";
  const isFailure = status === "error";
  const isRunning = status === "running";
  const high = decision === "high_confidence_possible_duplicate";
  const medium = decision === "medium_confidence_review";
  const low = decision === "low_confidence_related" || decision === "no_clear_duplicate_found";
  card.className = `proxy-status-card bilibili-duplicate-card ${
    isFailure ? "proxy-bad" : high || medium ? "proxy-ok" : low ? "alert-warn" : ""
  }`;

  const searchMeta = searchState === "search_unavailable"
    ? `搜索通道受限 · 候选 ${candidates.length} 个 · Top score ${report.scoring_summary?.top_score ?? 0}`
    : searchSummary.searched
      ? `已搜索 ${searchSummary.successful_query_count || 0}/${searchSummary.attempted_query_count || 0} 个查询 · 可解析候选 ${searchSummary.parsed_candidate_count || 0} 个 · Top score ${report.scoring_summary?.top_score ?? 0}`
      : `未触发搜索 · 候选 ${candidates.length} 个 · Top score ${report.scoring_summary?.top_score ?? 0}`;

  const title = isFailure
    ? "Bilibili 检测失败"
    : isRunning
      ? "Bilibili 检测中"
      : bilibiliSearchStateLabel(searchState, decision);
  const meta = isRunning
    ? "正在生成查询并轻量搜索 B 站"
    : isFailure
      ? escapeHtml(stateValue.error || "检测失败")
      : searchMeta;

  const bestHtml = best
    ? `<div class="bilibili-best">
        <div class="bilibili-score">${escapeHtml(best.score ?? 0)}</div>
        <div>
          <strong>${escapeHtml(best.title || "未命名候选")}</strong>
          <div class="bilibili-meta">${escapeHtml(best.uploader || "未知 UP")} · ${escapeHtml(best.duration || seconds(best.duration_seconds || 0))} · ${escapeHtml(best.published_at || "未知发布时间")}</div>
          <div class="bilibili-reasons">${(best.reason_codes || []).map((code) => `<span>${escapeHtml(code)}</span>`).join("")}</div>
        </div>
      </div>`
    : "";

  const rows = candidates
    .map((candidate, index) => {
      const url = candidate.url || "";
      const searchUrl = candidate.source_search_url || query.search_url || "";
      const noteId = `bilibiliFeedbackNote-${index}`;
      return `<div class="bilibili-candidate">
        <div class="bilibili-candidate-main">
          <strong>${escapeHtml(candidate.title || "未命名候选")}</strong>
          <div class="bilibili-meta">${escapeHtml(candidate.uploader || "未知 UP")} · ${escapeHtml(candidate.duration || seconds(candidate.duration_seconds || 0))} · ${escapeHtml(candidate.published_at || "未知发布时间")}</div>
          <div class="bilibili-reasons">${(candidate.reason_codes || []).slice(0, 5).map((code) => `<span>${escapeHtml(code)}</span>`).join("")}</div>
          <div class="bilibili-feedback">
            <input id="${noteId}" type="text" placeholder="备注" />
            <button class="mini-btn" type="button" data-bilibili-feedback="${index}" data-label="duplicate">重复</button>
            <button class="mini-btn" type="button" data-bilibili-feedback="${index}" data-label="not_duplicate">不重复</button>
            <button class="mini-btn" type="button" data-bilibili-feedback="${index}" data-label="same_topic">同主题</button>
            <button class="mini-btn" type="button" data-bilibili-feedback="${index}" data-label="manual_review">复核</button>
          </div>
        </div>
        <div class="bilibili-candidate-actions">
          <span class="bilibili-score-small">${escapeHtml(candidate.score ?? 0)}</span>
          ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">打开视频</a>` : ""}
          ${searchUrl ? `<a href="${escapeHtml(searchUrl)}" target="_blank" rel="noreferrer">打开搜索</a>` : ""}
        </div>
      </div>`;
    })
    .join("");

  const fallbackLinks = (report.queries || report.query_plan || [])
    .slice(0, 5)
    .map((item) => item.search_url)
    .filter(Boolean);
  const fallbackHtml =
    fallbackLinks.length
      ? `<div class="bilibili-manual-review">
          <strong>手动复核入口</strong>
          <div class="bilibili-fallback">${fallbackLinks.map((url, index) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">手动搜索 ${index + 1}</a>`).join("")}</div>
        </div>`
      : "";
  const stateHtml = `
    <div class="bilibili-state-row">
      <span>真实搜索状态</span>
      <strong>${escapeHtml(searchState || (searchSummary.searched ? "searched_no_parseable_candidates" : "unknown"))}</strong>
      <span>尝试查询</span>
      <strong>${escapeHtml(searchSummary.attempted_query_count ?? 0)}</strong>
      <span>可解析候选</span>
      <strong>${escapeHtml(searchSummary.parsed_candidate_count ?? candidates.length)}</strong>
    </div>
  `;
  const emptyCandidateHtml =
    !rows && !isRunning
      ? `<div class="entity-empty">没有解析到候选；请查看真实搜索状态，并使用下方手动复核入口继续判断。</div>`
      : "";

  card.innerHTML = `
    <div class="proxy-status-head">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(report.created_at || "")}</span>
    </div>
    <div class="proxy-status-meta">${meta}</div>
    <div class="bilibili-state-row"><span>工作流关系</span><strong>${escapeHtml(policyText)}</strong></div>
    ${stateHtml}
    ${bestHtml}
    ${rows ? `<div class="bilibili-candidates">${rows}</div>` : emptyCandidateHtml}
    ${fallbackHtml}
    ${stateValue.report_path ? `<div class="path-note">${escapeHtml(stateValue.report_path)}</div>` : ""}
  `;
  card.classList.remove("hidden");
  card.querySelectorAll("[data-bilibili-feedback]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.bilibiliFeedback);
      const label = button.dataset.label || "";
      const note = card.querySelector(`#bilibiliFeedbackNote-${index}`)?.value || "";
      saveBilibiliFeedback(index, label, note);
    });
  });
  revealNewNode("statusCards", `bilibili:${status}:${decision}:${report.created_at || stateValue.error || ""}`, card);
}

function saveBilibiliFeedback(candidateIndex, label, humanNote) {
  const current = state.bilibiliDuplicate || {};
  const report = current.report || {};
  const candidates = Array.isArray(report.candidates) ? report.candidates : [];
  const candidate = candidates[candidateIndex];
  if (!candidate) return;
  fetch("/api/bilibili-duplicate-feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      report,
      candidate,
      label,
      human_note: humanNote,
      report_path: current.report_path || "",
      output_dir: current.output_dir || "",
    }),
  })
    .then((res) => res.json())
    .then((payload) => {
      if (!payload.ok) {
        showToast(payload.error || "反馈保存失败");
        return;
      }
      showToast(`反馈已保存：${label}`);
    })
    .catch((error) => {
      showToast(`反馈保存失败：${error.message || error}`);
    });
}

function runBilibiliDuplicateSearch() {
  const url = el("downloadUrlInput").value.trim();
  if (!url) return;
  const button = el("bilibiliDuplicateSearchBtn");
  if (button) button.disabled = true;
  state.bilibiliDuplicate = { status: "running" };
  renderBilibiliDuplicate();
  fetch("/api/bilibili-duplicate-search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url,
      config: readFormConfig(),
      youtube_meta: state.youtubeMeta && !state.youtubeMeta.error ? state.youtubeMeta : null,
    }),
  })
    .then((res) => res.json())
    .then((payload) => {
      if (!payload.ok) {
        state.bilibiliDuplicate = {
          status: "error",
          error: payload.error || "Bilibili 检测失败",
          report: null,
          workflow_policy: payload.workflow_policy || null,
        };
        renderBilibiliDuplicate();
        showToast(payload.error || "Bilibili 检测失败");
        return;
      }
      state.bilibiliDuplicate = {
        status: "done",
        report: payload.report || {},
        workflow_policy: payload.workflow_policy || null,
        report_path: payload.report_path || "",
        candidates_tsv_path: payload.candidates_tsv_path || "",
        output_dir: payload.output_dir || "",
      };
      renderBilibiliDuplicate();
      showToast("Bilibili 检测完成");
    })
    .catch((error) => {
      state.bilibiliDuplicate = {
        status: "error",
        error: error.message || String(error),
        report: null,
      };
      renderBilibiliDuplicate();
      showToast(`Bilibili 检测失败：${error.message || error}`);
    })
    .finally(() => {
      if (button) button.disabled = false;
    });
}

window.__autosubRunBilibiliDuplicateSearch = runBilibiliDuplicateSearch;

const bilibiliDuplicateButton = el("bilibiliDuplicateSearchBtn");
if (bilibiliDuplicateButton) {
  bilibiliDuplicateButton.addEventListener("click", runBilibiliDuplicateSearch);
}

function renderRuntime(runtime, lastError) {
  const title = humanRunStateLabel(runtime?.stage_key, runtime?.title);
  const progress = Math.max(0, Math.min(100, Number(runtime?.overall_progress || 0)));
  const flow = state.flowControl || {};
  const flowDescription = flow.paused
    ? `已在安全检查点暂停${flow.pause_stage ? `：${flow.pause_stage}` : ""}。点击“继续翻译”恢复。`
    : flow.pause_requested
      ? "已收到暂停请求；ASR/FFmpeg 等不可安全中断步骤会在当前步骤结束后暂停。"
      : "";
  const description = flowDescription || runtime?.recovery?.message || lastError?.message || runtime?.description || "等待开始新的任务。";
  setRunState(title, normalizeRunState(runtime, lastError));
  el("currentStageLabel").textContent = `当前阶段：${title}`;
  el("currentStageDescription").textContent = description;
  el("overallProgressLabel").textContent = `总进度 ${progress}%`;
  el("overallProgressFill").style.width = `${progress}%`;
  renderErrorCard(lastError);
}

function renderInputDownloadPanel() {
  renderProxyStatus();
  renderIdmStatus();
  renderYoutubeMeta();
  renderBilibiliDuplicate();
}

function renderState(payload) {
  const safePayload = payload && typeof payload === "object" ? payload : {};
  const safeState = safePayload.state && typeof safePayload.state === "object" ? safePayload.state : {};
  if (Array.isArray(safePayload.jobs)) {
    state.jobs = safePayload.jobs;
  }
  if (Object.prototype.hasOwnProperty.call(safePayload, "active_job")) {
    state.activeJob = safePayload.active_job || null;
  }
  if (Array.isArray(safePayload.workflow_profiles)) {
    state.workflowProfiles = safePayload.workflow_profiles;
    renderWorkflowProfiles();
  }
  if (typeof safePayload.active_prompt_profile === "string") {
    state.activePromptProfile = safePayload.active_prompt_profile;
  }
  if (safePayload.active_dataset_profile && typeof safePayload.active_dataset_profile === "object") {
    state.activeDatasetProfile = safePayload.active_dataset_profile;
  }
  if (safePayload.flow_control && typeof safePayload.flow_control === "object") {
    state.flowControl = {
      ...state.flowControl,
      ...safePayload.flow_control,
    };
  }
  if (safePayload.openai_runtime && typeof safePayload.openai_runtime === "object") {
    state.openaiRuntime = safePayload.openai_runtime;
  }
  state.runtime = safeState.runtime || {};
  const runtime = safeState.runtime || {};
  renderRuntime(runtime, safeState.last_error || null);
  setTaskButtonsDisabled(taskIsBusy(runtime));
  renderStageFeed(safeState.history || []);
  renderQueue(safeState.queue || []);
  renderPhaseStatus(safeState.phase_status || {});
  renderJobs(state.jobs, state.activeJob);
  if (safePayload.projects) renderProjects(safePayload.projects);
  if (safePayload.videos) {
    const incomingVideos = Array.isArray(safePayload.videos) ? safePayload.videos : [];
    const previousPaths = new Set((state.videos || []).map((video) => video.path));
    const newVideos = incomingVideos.filter((video) => previousPaths.size && !previousPaths.has(video.path));
    if (newVideos.length) {
      state.selectedVideo = newVideos[newVideos.length - 1];
      state.selectedMediaInfo = null;
      state.inputListCollapsed = true;
    }
    renderVideos(incomingVideos);
  }
  state.selectedVideoProject = findProjectForSelectedVideo();
  state.selectedVideoProjectPath = state.selectedVideoProject?.path || null;
  fillFormIfClean(safePayload.config || state.config || DEFAULT_UI_CONFIG);
  updateFileActionButtons();
  renderInputDownloadPanel();
  renderWorkflowSummary();
  renderAdvancedStrategySummary();
  renderLocalFeedbackSummary(state.localFeedbackSummary);
  renderFeedbackReviewPanel();
  renderLearningQualityPanel();
  renderOpenAiRuntimeStatus();
  renderCommandContext();
}

function renderStateIfUseful(payload) {
  if (!payload || typeof payload !== "object") return;
  const hasActiveJob = Object.prototype.hasOwnProperty.call(payload, "active_job");
  if (payload.state || payload.jobs || hasActiveJob || payload.projects || payload.videos || payload.config) {
    renderState(payload);
  }
}

async function pauseFlow() {
  const pauseBtn = el("pauseFlowBtn");
  if (pauseBtn) pauseBtn.disabled = true;
  try {
    const response = await fetch("/api/pause", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "user_requested" }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      showToast(payload?.error || "暂停请求失败");
      return;
    }
    state.flowControl = { ...state.flowControl, ...(payload.flow_control || {}) };
    renderState(payload);
    showToast("已请求暂停，会在安全检查点生效");
  } catch (error) {
    showToast(`暂停请求失败：${error.message || error}`);
  } finally {
    renderFlowControlButtons();
  }
}

async function resumeFlow() {
  const resumeBtn = el("resumeFlowBtn");
  if (resumeBtn) resumeBtn.disabled = true;
  try {
    const response = await fetch("/api/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      showToast(payload?.error || "继续翻译失败");
      return;
    }
    state.flowControl = { ...state.flowControl, ...(payload.flow_control || {}) };
    renderState(payload);
    showToast("已继续翻译");
  } catch (error) {
    showToast(`继续翻译失败：${error.message || error}`);
  } finally {
    renderFlowControlButtons();
  }
}

async function cancelCurrentJob() {
  const cancelBtn = el("cancelJobBtn");
  if (cancelBtn) cancelBtn.disabled = true;
  try {
    const response = await fetch("/api/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      showToast(payload?.error || "取消任务失败");
      return;
    }
    renderState(payload);
    showToast("已请求取消当前任务");
  } catch (error) {
    showToast(`取消任务失败：${error.message || error}`);
  } finally {
    renderJobControls();
  }
}

async function refreshOpenAiRuntimeStatus() {
  const button = el("refreshOpenAiRuntimeBtn");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/api/state");
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) {
      showToast(payload?.error || "OpenAI 运行环境检测失败");
      return;
    }
    renderState(payload);
    showToast("OpenAI 运行环境已重新检测");
  } catch (error) {
    showToast(`OpenAI 运行环境检测失败：${error.message || error}`);
  } finally {
    if (button) button.disabled = false;
  }
}

async function testProxy() {
  el("testProxyBtn").disabled = true;
  try {
    await fetch("/api/save-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readFormConfig()),
    }).catch(() => null);
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

async function checkIdm() {
  el("checkIdmBtn").disabled = true;
  try {
    const response = await fetch("/api/check-idm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: readFormConfig() }),
    });
    const payload = await response.json();
    state.idmStatus = payload.idm || null;
    renderIdmStatus();
  } catch {
    state.idmStatus = {
      ok: false,
      configured_path: el("idm_exe_path").value,
      resolved_path: "",
      output_dir: el("idm_output_dir").value,
      output_dir_exists: false,
      output_dir_writable: false,
    };
    renderIdmStatus();
  } finally {
    el("checkIdmBtn").disabled = false;
  }
}

function refreshBootstrap() {
  return fetch("/api/bootstrap")
    .then((res) => res.json())
    .then((payload) => {
      renderState(payload);
      return payload;
    })
    .catch(() => null);
}

function bootstrap() {
  fillForm(DEFAULT_UI_CONFIG);
  renderState({
    state: { runtime: {}, history: [], queue: [], phase_status: {} },
    config: DEFAULT_UI_CONFIG,
    workflow_profiles: state.workflowProfiles,
    active_prompt_profile: state.activePromptProfile,
    active_dataset_profile: state.activeDatasetProfile,
    videos: [],
    projects: [],
  });
  startPolling();
  fetch("/api/bootstrap")
    .then((res) => res.json())
    .then((payload) => {
      renderState(payload);
    })
    .catch(() => {
      renderState({
        state: {
          runtime: {
            stage_key: "idle",
            title: "离线",
            description: "暂时无法连接本地服务，页面已加载默认配置。",
            overall_progress: 0,
          },
          history: [],
          queue: [],
          phase_status: {},
          last_error: null,
        },
        config: DEFAULT_UI_CONFIG,
        workflow_profiles: state.workflowProfiles,
        active_prompt_profile: state.activePromptProfile,
        active_dataset_profile: state.activeDatasetProfile,
        videos: [],
        projects: [],
      });
    });
}

function startPolling() {
  if (state.polling) clearInterval(state.polling);
  state.pollCount = 0;
  state.polling = setInterval(() => {
    fetch("/api/state")
      .then((res) => res.json())
      .then((payload) => {
        renderState(payload);
        state.pollCount += 1;
        if (state.pollCount % 10 === 0) {
          fetch("/api/bootstrap")
            .then((res) => res.json())
            .then((fullPayload) => renderState(fullPayload))
            .catch(() => {});
        }
      })
      .catch(() => {});
  }, 1800);
}

function bindTabs() {
  const switchPanel = (panel) => {
    if (!panel) return;
    document.querySelectorAll(".tab").forEach((node) => {
      const active = node.dataset.panel === panel;
      node.classList.toggle("active", active);
      node.setAttribute("aria-selected", active ? "true" : "false");
      if (active) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
    document.querySelectorAll(".nav-item").forEach((node) => {
      const active = node.dataset.panel === panel;
      node.classList.toggle("active", active);
      if (active) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
    document.querySelectorAll(".workspace-panel").forEach((node) => {
      node.classList.toggle("active", node.dataset.panel === panel);
    });
  };

  document.querySelectorAll(".tab, .nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = btn.dataset.panel;
      if (!panel) return;
      switchPanel(panel);
      if (panel === "feedback-review") refreshFeedbackReview();
      if (panel === "learning-quality") refreshLearningQualitySummary();
      scrollToWorkspaceDetails();
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
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const message = payload?.error || payload?.message || `${endpoint} failed (${response.status})`;
      throw new Error(message);
    }
    return payload;
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
    try {
      const payload = await uploadFile("/api/upload-video", file);
      if (!payload.ok) return;
      state.selectedVideo = payload.video;
      state.selectedMediaInfo = null;
      state.inputListCollapsed = true;
      renderState(payload);
      showToast("Input 已添加");
    } catch (error) {
      showToast(`添加 Input 失败：${error.message || error}`);
    }
  });

  audioInput.addEventListener("change", async () => {
    const file = audioInput.files?.[0];
    if (!file) return;
    try {
      const payload = await uploadFile("/api/upload-audio", file);
      if (!payload.ok) return;
      el("audio_override_path").value = payload.audio.path;
      setLinkedAudioLabel(payload.audio.path);
      inspectSelectedVideo();
      showToast("MP3 已添加");
    } catch (error) {
      showToast(`添加 MP3 失败：${error.message || error}`);
    }
  });

  const openOutput = () => {
    const projectPath = state.selectedFileProjectPath || state.selectedProject?.path || state.projects[0]?.path || null;
    fetch("/api/open-output", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    });
  };

  const openInput = () => {
    fetch("/api/open-input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  };

  const fetchYoutubeInfo = () => {
    const url = el("downloadUrlInput").value.trim();
    if (!url) return;
    fetch("/api/youtube-meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, config: readFormConfig() }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) {
          state.youtubeMeta = { error: payload.error || "YouTube 信息获取失败", mode: state.proxyStatus?.mode || "" };
          renderYoutubeMeta();
          showToast(payload.error || "YouTube 信息获取失败");
          return;
        }
        state.youtubeMeta = { ...(payload.meta || {}), output_dir: payload.output_dir, output_path: payload.output_path, info_path: payload.info_path, info_text: payload.info_text, cover_path: payload.cover_path };
        renderYoutubeMeta();
        showToast("信息已获取");
      })
      .catch((error) => {
        state.youtubeMeta = { error: error.message || String(error), mode: state.proxyStatus?.mode || "" };
        renderYoutubeMeta();
        showToast(`YouTube 信息获取失败：${error.message || error}`);
      });
  };

  const fetchYoutubeCover = () => {
    const url = el("downloadUrlInput").value.trim();
    if (!url) return;
    fetch("/api/youtube-cover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, config: readFormConfig() }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) {
          state.youtubeMeta = { error: payload.error || "YouTube 封面获取失败", mode: state.proxyStatus?.mode || "" };
          renderYoutubeMeta();
          showToast(payload.error || "YouTube 封面获取失败");
          return;
        }
        state.youtubeMeta = { ...(payload.meta || {}), output_dir: payload.output_dir, output_path: payload.output_path, info_path: payload.info_path, cover_path: payload.cover_path, cover_1280x960_path: payload.cover_1280x960_path };
        renderYoutubeMeta();
        showToast("封面已获取");
      })
      .catch((error) => {
        state.youtubeMeta = { error: error.message || String(error), mode: state.proxyStatus?.mode || "" };
        renderYoutubeMeta();
        showToast(`YouTube 封面获取失败：${error.message || error}`);
      });
  };

  const rebuildPaddedCover = () => {
    const outputDir = state.youtubeMeta?.output_path || state.youtubeMeta?.output_dir || null;
    if (!outputDir) return;
    fetch("/api/rebuild-youtube-cover-1280x960", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: outputDir }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) return;
        state.youtubeMeta = { ...(state.youtubeMeta || {}), output_dir: payload.output_dir, output_path: payload.output_path, cover_path: payload.cover_path, cover_1280x960_path: payload.cover_1280x960_path };
        renderYoutubeMeta();
        showToast("1280x960 封面已重建");
      });
  };

  const scanInput = () => {
    const previousPaths = new Set((state.videos || []).map((video) => video.path));
    fetch("/api/scan-input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((res) => res.json())
      .then((payload) => {
        const incomingVideos = Array.isArray(payload.videos) ? payload.videos : [];
        const newVideos = incomingVideos.filter((video) => !previousPaths.has(video.path));
        if (newVideos.length) {
          state.selectedVideo = newVideos[newVideos.length - 1];
          state.selectedMediaInfo = null;
          state.inputListCollapsed = true;
        }
        renderState(payload);
        showToast("已扫描 input");
      });
  };

  const runDownload = (runAfterDownload) => {
    const url = el("downloadUrlInput").value.trim();
    if (!url) return;
    const config = readFormConfig();
    if (state.proxyStatus && !state.proxyStatus.ok && config.download_backend === "ytdlp") {
      showToast("代理检测失败，请先修复代理");
      return;
    }
    fetch("/api/download-video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        run_after_download: runAfterDownload,
        config,
      }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) {
          showToast(payload.error || "下载任务启动失败");
          return;
        }
        renderStateIfUseful(payload);
        refreshBootstrap();
      })
      .catch((error) => showToast(`下载任务启动失败：${error.message || error}`));
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
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) {
          showToast(payload.error || "流程启动失败");
          return;
        }
        renderStateIfUseful(payload);
        refreshBootstrap();
      })
      .catch((error) => showToast(`流程启动失败：${error.message || error}`));
  };

  el("pickInputBtn").addEventListener("click", pickInput);
  el("pickInputInlineBtn").addEventListener("click", pickInput);
  el("pickAudioBtn").addEventListener("click", pickAudio);
  el("pickAudioInlineBtn").addEventListener("click", pickAudio);
  el("workflow_profile")?.addEventListener("change", (event) => applyWorkflowProfileSelection(event.target.value));
  el("applyRussianWorkflowBtn")?.addEventListener("click", () => applyWorkflowProfileSelection("ru_to_zh_default"));
  ["subtitle_mode", "prompt_profile", "dataset_profile", "source_reference_label"].forEach((id) => {
    const node = el(id);
    if (!node) return;
    node.addEventListener("input", () => {
      markConfigDirty();
      renderWorkflowSummary();
    });
    node.addEventListener("change", () => {
      markConfigDirty();
      renderWorkflowSummary();
    });
  });
  el("openai_base_url")?.addEventListener("input", renderOpenAiRuntimeStatus);
  el("previewBtn").addEventListener("click", () => runPipeline(60));
  el("pauseFlowBtn")?.addEventListener("click", pauseFlow);
  el("resumeFlowBtn")?.addEventListener("click", resumeFlow);
  el("cancelJobBtn")?.addEventListener("click", cancelCurrentJob);
  el("downloadOnlyBtn").addEventListener("click", () => runDownload(false));
  el("downloadAndRunBtn").addEventListener("click", () => runDownload(true));
  el("testProxyBtn").addEventListener("click", testProxy);
  el("checkIdmBtn").addEventListener("click", checkIdm);
  el("fetchYoutubeInfoBtn").addEventListener("click", fetchYoutubeInfo);
  el("fetchYoutubeCoverBtn").addEventListener("click", fetchYoutubeCover);
  el("rebuildPaddedCoverBtn").addEventListener("click", rebuildPaddedCover);
  el("openInputBtn").addEventListener("click", openInput);
  el("scanInputBtn").addEventListener("click", scanInput);
  el("toggleInputListBtn")?.addEventListener("click", () => {
    state.inputListCollapsed = !state.inputListCollapsed;
    renderVideos(state.videos);
  });
  el("openYoutubeOutputBtn").addEventListener("click", () => {
    const outputDir = state.youtubeMeta?.output_path || state.youtubeMeta?.output_dir || null;
    if (!outputDir) return;
    fetch("/api/open-output", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: outputDir }),
    });
  });
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
        state.selectedFileProjectPath = null;
        state.selectedVideo = null;
        state.selectedMediaInfo = null;
        renderState(payload);
      });
  });
  el("openOutputBtn").addEventListener("click", openOutput);
  el("openOutputInlineBtn").addEventListener("click", openOutput);
  el("learnStyleBtn").addEventListener("click", () => {
    const projectPath = state.selectedFileProjectPath || state.selectedProject?.path || null;
    if (!projectPath) return;
    fetch("/api/learn-style", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) return;
        renderProjects(state.projects);
        showToast(payload.message || "风格样例已生成");
      });
  });
  el("collectStyleFeedbackBtn")?.addEventListener("click", () => {
    collectLocalFeedback("ass");
  });
  el("collectSpanFeedbackBtn")?.addEventListener("click", () => {
    collectLocalFeedback("span");
  });
  el("feedbackReviewKind")?.addEventListener("change", (event) => {
    state.feedbackReview.kind = event.target.value || "style";
    refreshFeedbackReview();
  });
  el("feedbackReviewStatus")?.addEventListener("change", (event) => {
    state.feedbackReview.status = event.target.value || "pending";
    refreshFeedbackReview();
  });
  el("refreshFeedbackReviewBtn")?.addEventListener("click", refreshFeedbackReview);
  el("refreshLearningQualityBtn")?.addEventListener("click", refreshLearningQualitySummary);
  el("reburnFromInputBtn").addEventListener("click", () => {
    const projectPath = state.selectedVideoProjectPath || null;
    if (!projectPath) return;
    fetch("/api/reburn-from-ass", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) return;
        renderStateIfUseful(payload);
        refreshBootstrap();
        showToast("已开始按当前双语 ASS 重新烧录");
      });
  });
  el("reburnFromAssBtn").addEventListener("click", () => {
    const projectPath = state.selectedFileProjectPath || state.selectedProject?.path || null;
    if (!projectPath || !state.selectedFilePath || !/\.ass$/i.test(state.selectedFilePath)) return;
    fetch("/api/reburn-from-ass", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: projectPath }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) return;
        renderStateIfUseful(payload);
        refreshBootstrap();
        showToast("已开始重新烧录");
      });
  });

  el("saveConfigBtn").addEventListener("click", () => {
    const config = readFormConfig();
    state.configSaveState = "saving";
    renderConfigSaveState();
    fetch("/api/save-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) {
          state.configSaveState = "dirty";
          renderConfigSaveState();
          showToast(payload.error || "保存配置失败");
          return;
        }
        clearConfigDirty(payload.config || config);
        fillForm(payload.config || config);
        showToast("配置已保存");
      })
      .catch((error) => {
        state.configSaveState = "dirty";
        renderConfigSaveState();
        showToast(`保存配置失败：${error.message || error}`);
      });
  });
  el("saveConfigBottomBtn").addEventListener("click", () => el("saveConfigBtn").click());

  el("runBtn").addEventListener("click", () => runPipeline(null));
}

function bindSubtitleStyleControls() {
  syncColorInputs("zh_primary_color", "#FFF2A6");
  syncColorInputs("zh_outline_color", "#202020");
  syncColorInputs("zh_shadow_color", "#000000");
  syncOpacityInput("zh_primary_opacity", 100);
  syncOpacityInput("zh_outline_opacity", 45);
  syncOpacityInput("zh_shadow_opacity", 35);
  ["zh_font_name", "zh_font_size", "zh_outline_width", "zh_shadow_depth"].forEach((id) => {
    const node = el(id);
    if (node) node.addEventListener("input", updateSubtitleStylePreview);
  });
  el("resetZhColorBtn").addEventListener("click", () => {
    setColorField("zh_primary_color", "#FFF2A6", "#FFF2A6");
    setOpacityField("zh_primary_opacity", 100, 100);
    setColorField("zh_outline_color", "#202020", "#202020");
    setOpacityField("zh_outline_opacity", 45, 45);
    setColorField("zh_shadow_color", "#000000", "#000000");
    setOpacityField("zh_shadow_opacity", 35, 35);
    el("zh_outline_width").value = 1.8;
    el("zh_shadow_depth").value = 0.4;
    updateSubtitleStylePreview();
    markConfigDirty();
  });
}

function bindConfigInputs() {
  document.querySelectorAll("input, textarea, select").forEach((node) => {
    if (!node.id) return;
    if (["videoFileInput", "audioFileInput", "feedbackReviewKind", "feedbackReviewStatus"].includes(node.id)) return;
    if (node.id.endsWith("_value")) return;
    const eventName = node.type === "checkbox" || node.tagName === "SELECT" ? "change" : "input";
    node.addEventListener(eventName, () => {
      if (node.id === "audio_override_path") return;
      markConfigDirty();
    });
  });
}

bindTabs();
bindSubtitleStyleControls();
bindConfigInputs();
decorateStaticButtons();
bindActions();
renderConfigSaveState();
renderAdvancedStrategySummary();
renderLocalFeedbackSummary(null);
renderFeedbackReviewPanel();
renderLearningQualityPanel();
revealMotionNodes();
refreshLocalFeedbackSummary();
refreshLearningQualitySummary();
bootstrap();
