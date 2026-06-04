const state = {
  config: null,
  workflowProfiles: [],
  activePromptProfile: "",
  activeDatasetProfile: null,
  videos: [],
  audios: [],
  projects: [],
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
  selectedMediaInfo: null,
  mediaInspectToken: 0,
  lastErrorPayload: null,
  runtime: null,
  pollCount: 0,
  formDirty: false,
  configSaveState: "saved",
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
  audio_override_path: "",
  preview_seconds: null,
  load_existing_segments: false,
  force_retranslate_existing_segments: false,
  skip_burn: false,
  repair_high_risk_spans: true,
  span_repair_max_spans: 12,
  enable_ai_display_rewrite: false,
  display_rewrite_max_ai_segments: 12,
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
    zh_primary_color: "#FFFFFF",
    zh_primary_opacity: 100,
    zh_outline_color: "#141414",
    zh_outline_opacity: 100,
    zh_shadow_color: "#000000",
    zh_shadow_opacity: 60,
    zh_outline_width: 2.2,
    zh_shadow_depth: 0.6,
    zh_margin_l: 90,
    zh_margin_r: 90,
    zh_margin_v: 94,
    zh_wrap_trigger_chars: 32,
    zh_max_chars_per_line: 28,
    zh_max_lines: 2,
    en_font_name: "Arial",
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

function safeText(value) {
  return value || "";
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setRunState(stateText) {
  el("serverState").textContent = stateText;
  el("runStatePill").textContent = stateText;
}

function setTaskButtonsDisabled(disabled) {
  ["runBtn", "previewBtn", "downloadOnlyBtn", "downloadAndRunBtn"].forEach((id) => {
    const node = el(id);
    if (node) node.disabled = disabled;
  });
}

function taskIsBusy(runtime) {
  return !["idle", "complete", "error", "recovered_state"].includes(String(runtime?.stage_key || "idle"));
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

function renderConfigSaveState() {
  const node = el("configSaveState");
  if (!node) return;
  if (state.configSaveState === "saving") {
    node.textContent = "正在保存当前配置";
    node.className = "config-save-state saving";
    return;
  }
  const dirty = state.configSaveState === "dirty";
  node.textContent = dirty ? "当前配置未保存" : "当前配置已保存";
  node.className = `config-save-state ${dirty ? "dirty" : "saved"}`;
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
    primaryColor: readColorField("zh_primary_color", "#FFFFFF"),
    primaryOpacity: readOpacityField("zh_primary_opacity", 100),
    outlineColor: readColorField("zh_outline_color", "#141414"),
    outlineOpacity: readOpacityField("zh_outline_opacity", 100),
    shadowColor: readColorField("zh_shadow_color", "#000000"),
    shadowOpacity: readOpacityField("zh_shadow_opacity", 60),
    outlineWidth: clampNumber(el("zh_outline_width")?.value, 0, 12, 2.2),
    shadowDepth: clampNumber(el("zh_shadow_depth")?.value, 0, 12, 0.6),
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
    audio_override_path: el("audio_override_path").value,
    preview_seconds: el("preview_seconds").value ? Number(el("preview_seconds").value) : null,
    load_existing_segments: el("load_existing_segments").checked,
    force_retranslate_existing_segments: el("force_retranslate_existing_segments").checked,
    skip_burn: el("skip_burn").checked,
    repair_high_risk_spans: el("repair_high_risk_spans").checked,
    span_repair_max_spans: Number(el("span_repair_max_spans").value || 12),
    enable_ai_display_rewrite: el("enable_ai_display_rewrite").checked,
    display_rewrite_max_ai_segments: Number(el("display_rewrite_max_ai_segments").value || 12),
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
      zh_primary_color: readColorField("zh_primary_color", "#FFFFFF"),
      zh_primary_opacity: readOpacityField("zh_primary_opacity", 100),
      zh_outline_color: readColorField("zh_outline_color", "#141414"),
      zh_outline_opacity: readOpacityField("zh_outline_opacity", 100),
      zh_shadow_color: readColorField("zh_shadow_color", "#000000"),
      zh_shadow_opacity: readOpacityField("zh_shadow_opacity", 60),
      zh_outline_width: Number(el("zh_outline_width").value || 2.2),
      zh_shadow_depth: Number(el("zh_shadow_depth").value || 0.6),
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
  el("audio_override_path").value = config.audio_override_path || "";
  el("preview_seconds").value = config.preview_seconds ?? "";
  el("load_existing_segments").checked = Boolean(config.load_existing_segments);
  el("force_retranslate_existing_segments").checked = Boolean(config.force_retranslate_existing_segments);
  el("skip_burn").checked = Boolean(config.skip_burn);
  el("repair_high_risk_spans").checked = config.repair_high_risk_spans !== false;
  el("span_repair_max_spans").value = config.span_repair_max_spans ?? 12;
  el("enable_ai_display_rewrite").checked = Boolean(config.enable_ai_display_rewrite);
  el("display_rewrite_max_ai_segments").value = config.display_rewrite_max_ai_segments ?? 12;
  el("download_backend").value = config.download_backend || "auto";
  el("idm_exe_path").value = config.idm_exe_path || "";
  el("idm_output_dir").value = config.idm_output_dir || "";
  el("idm_wait_timeout_seconds").value = config.idm_wait_timeout_seconds ?? 1800;

  const style = config.style || {};
  el("zh_font_name").value = style.zh_font_name || "Maple Mono NF CN";
  el("zh_font_size").value = style.zh_font_size ?? 64;
  setColorField("zh_primary_color", style.zh_primary_color || "#FFFFFF", "#FFFFFF");
  setOpacityField("zh_primary_opacity", style.zh_primary_opacity ?? 100, 100);
  setColorField("zh_outline_color", style.zh_outline_color || "#141414", "#141414");
  setOpacityField("zh_outline_opacity", style.zh_outline_opacity ?? 100, 100);
  setColorField("zh_shadow_color", style.zh_shadow_color || "#000000", "#000000");
  setOpacityField("zh_shadow_opacity", style.zh_shadow_opacity ?? 60, 60);
  el("zh_outline_width").value = style.zh_outline_width ?? 2.2;
  el("zh_shadow_depth").value = style.zh_shadow_depth ?? 0.6;
  el("zh_margin_l").value = style.zh_margin_l ?? 90;
  el("zh_margin_r").value = style.zh_margin_r ?? 90;
  el("zh_margin_v").value = style.zh_margin_v ?? 94;
  el("zh_wrap_trigger_chars").value = style.zh_wrap_trigger_chars ?? 32;
  el("zh_max_chars_per_line").value = style.zh_max_chars_per_line ?? 28;
  el("zh_max_lines").value = style.zh_max_lines ?? 2;
  el("en_font_name").value = style.en_font_name || "Arial";
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
}

function formatWorkflowDatasetPreview(dataset) {
  if (!dataset || typeof dataset !== "object") return "No dataset profile loaded.";
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
  return lines.join("\n\n") || "No dataset preview available.";
}

function getSelectedWorkflowProfile() {
  const workflowId = el("workflow_profile")?.value || state.config?.workflow_profile || "en_to_zh_default";
  return state.workflowProfiles.find((item) => item.id === workflowId) || null;
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
  const promptNode = el("workflowPromptPreview");
  const datasetNode = el("workflowDatasetPreview");
  const descriptionNode = el("workflowProfileDescription");
  const pairNode = el("workflow_pair_preview");
  const currentPromptProfile = el("prompt_profile")?.value || state.config?.prompt_profile || "";
  const currentDatasetProfile = el("dataset_profile")?.value || state.config?.dataset_profile || "";
  const profileOwnsPrompt = profile && profile.prompt_profile === currentPromptProfile;
  const profileOwnsDataset = profile && profile.dataset_profile === currentDatasetProfile;
  if (descriptionNode) {
    descriptionNode.textContent = profile?.description || "Choose a workflow profile to load language-aware defaults.";
  }
  if (promptNode) {
    const text = profileOwnsPrompt
      ? (profile?.prompt_preview || state.activePromptProfile || el("translation_prompt")?.value || "")
      : (el("translation_prompt")?.value || "");
    promptNode.textContent = text ? text.slice(0, 900) : "No prompt loaded.";
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

function humanRunStateLabel(stageKey, title) {
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
  if (state.selectedVideo.path !== previousPath || !state.selectedMediaInfo) {
    inspectSelectedVideo();
  }
  renderInputAssStatus();
}

function renderVideos(videos) {
  state.videos = videos;
  syncSelectedVideo(videos);
  state.selectedVideoProject = findProjectForSelectedVideo();
  state.selectedVideoProjectPath = state.selectedVideoProject?.path || null;
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
  });

  renderChunkPanel(phaseStatus?.translation);
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
      state.selectedFileProjectPath = project.path;
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
}

function renderRuntime(runtime, lastError) {
  const title = humanRunStateLabel(runtime?.stage_key, runtime?.title);
  const progress = Math.max(0, Math.min(100, Number(runtime?.overall_progress || 0)));
  const description = runtime?.recovery?.message || lastError?.message || runtime?.description || "等待开始新的任务。";
  setRunState(title);
  el("currentStageLabel").textContent = `当前阶段：${title}`;
  el("currentStageDescription").textContent = description;
  el("overallProgressLabel").textContent = `总进度 ${progress}%`;
  el("overallProgressFill").style.width = `${progress}%`;
  renderErrorCard(lastError);
}

function renderState(payload) {
  const safePayload = payload && typeof payload === "object" ? payload : {};
  const safeState = safePayload.state && typeof safePayload.state === "object" ? safePayload.state : {};
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
  state.runtime = safeState.runtime || {};
  const runtime = safeState.runtime || {};
  renderRuntime(runtime, safeState.last_error || null);
  setTaskButtonsDisabled(taskIsBusy(runtime));
  renderStageFeed(safeState.history || []);
  renderQueue(safeState.queue || []);
  renderPhaseStatus(safeState.phase_status || {});
  if (safePayload.projects) renderProjects(safePayload.projects);
  if (safePayload.videos) renderVideos(safePayload.videos);
  state.selectedVideoProject = findProjectForSelectedVideo();
  state.selectedVideoProjectPath = state.selectedVideoProject?.path || null;
  fillFormIfClean(safePayload.config || state.config || DEFAULT_UI_CONFIG);
  updateFileActionButtons();
  renderProxyStatus();
  renderIdmStatus();
  renderYoutubeMeta();
  renderWorkflowSummary();
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
      });
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
      body: JSON.stringify({ url }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) return;
        state.youtubeMeta = { ...(payload.meta || {}), output_dir: payload.output_dir, output_path: payload.output_path, info_path: payload.info_path, info_text: payload.info_text, cover_path: payload.cover_path };
        renderYoutubeMeta();
        showToast("信息已获取");
      });
  };

  const fetchYoutubeCover = () => {
    const url = el("downloadUrlInput").value.trim();
    if (!url) return;
    fetch("/api/youtube-cover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
      .then((res) => res.json())
      .then((payload) => {
        if (!payload.ok) return;
        state.youtubeMeta = { ...(payload.meta || {}), output_dir: payload.output_dir, output_path: payload.output_path, info_path: payload.info_path, cover_path: payload.cover_path, cover_1280x960_path: payload.cover_1280x960_path };
        renderYoutubeMeta();
        showToast("封面已获取");
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
    fetch("/api/scan-input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((res) => res.json())
      .then((payload) => {
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
        if (!payload.ok) showToast(payload.error || "下载任务启动失败");
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
        if (!payload.ok) showToast(payload.error || "流程启动失败");
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
  el("previewBtn").addEventListener("click", () => runPipeline(60));
  el("downloadOnlyBtn").addEventListener("click", () => runDownload(false));
  el("downloadAndRunBtn").addEventListener("click", () => runDownload(true));
  el("testProxyBtn").addEventListener("click", testProxy);
  el("checkIdmBtn").addEventListener("click", checkIdm);
  el("fetchYoutubeInfoBtn").addEventListener("click", fetchYoutubeInfo);
  el("fetchYoutubeCoverBtn").addEventListener("click", fetchYoutubeCover);
  el("rebuildPaddedCoverBtn").addEventListener("click", rebuildPaddedCover);
  el("openInputBtn").addEventListener("click", openInput);
  el("scanInputBtn").addEventListener("click", scanInput);
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
  syncColorInputs("zh_primary_color", "#FFFFFF");
  syncColorInputs("zh_outline_color", "#141414");
  syncColorInputs("zh_shadow_color", "#000000");
  syncOpacityInput("zh_primary_opacity", 100);
  syncOpacityInput("zh_outline_opacity", 100);
  syncOpacityInput("zh_shadow_opacity", 60);
  ["zh_font_name", "zh_font_size", "zh_outline_width", "zh_shadow_depth"].forEach((id) => {
    const node = el(id);
    if (node) node.addEventListener("input", updateSubtitleStylePreview);
  });
  el("resetZhColorBtn").addEventListener("click", () => {
    setColorField("zh_primary_color", "#FFFFFF", "#FFFFFF");
    setOpacityField("zh_primary_opacity", 100, 100);
    setColorField("zh_outline_color", "#141414", "#141414");
    setOpacityField("zh_outline_opacity", 100, 100);
    setColorField("zh_shadow_color", "#000000", "#000000");
    setOpacityField("zh_shadow_opacity", 60, 60);
    el("zh_outline_width").value = 2.2;
    el("zh_shadow_depth").value = 0.6;
    updateSubtitleStylePreview();
    markConfigDirty();
  });
}

function bindConfigInputs() {
  document.querySelectorAll("input, textarea, select").forEach((node) => {
    if (!node.id) return;
    if (["videoFileInput", "audioFileInput"].includes(node.id)) return;
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
bindActions();
renderConfigSaveState();
bootstrap();
