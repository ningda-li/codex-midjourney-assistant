import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawn } from "node:child_process";

const SCRIPT_ROOT = path.dirname(new URL(import.meta.url).pathname.replace(/\//g, path.sep).replace(/^\\([A-Za-z]:\\)/, "$1"));
const CODEX_HOME = path.resolve(SCRIPT_ROOT, "..", "..", "..");
const MEMORY_ROOT = path.join(CODEX_HOME, "memories", "midjourney-assistant");
const ISOLATED_BROWSER_ROOT = path.join(MEMORY_ROOT, "isolated-browser");
const LEGACY_EDGE_PROFILE_DIR = path.join(ISOLATED_BROWSER_ROOT, "edge-profile");
const PROFILES_ROOT = path.join(ISOLATED_BROWSER_ROOT, "profiles");
const DEFAULT_STATE_PATH = path.join(ISOLATED_BROWSER_ROOT, "runtime-state.json");
const DEFAULT_PAGE_URL = "https://www.midjourney.com/imagine";
const DEFAULT_PORT = 9230;
const SUPPORTED_BROWSERS = [
  {
    key: "edge",
    name: "Edge",
    processName: "msedge.exe",
    pathCandidates: [
      path.join(process.env["ProgramFiles(x86)"] || "", "Microsoft", "Edge", "Application", "msedge.exe"),
      path.join(process.env.ProgramFiles || "", "Microsoft", "Edge", "Application", "msedge.exe"),
    ],
  },
  {
    key: "chrome",
    name: "Chrome",
    processName: "chrome.exe",
    pathCandidates: [
      path.join(process.env.ProgramFiles || "", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env["ProgramFiles(x86)"] || "", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
    ],
  },
  {
    key: "brave",
    name: "Brave",
    processName: "brave.exe",
    pathCandidates: [
      path.join(process.env.ProgramFiles || "", "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
      path.join(process.env["ProgramFiles(x86)"] || "", "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
      path.join(process.env.LOCALAPPDATA || "", "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    ],
  },
  {
    key: "vivaldi",
    name: "Vivaldi",
    processName: "vivaldi.exe",
    pathCandidates: [
      path.join(process.env.ProgramFiles || "", "Vivaldi", "Application", "vivaldi.exe"),
      path.join(process.env["ProgramFiles(x86)"] || "", "Vivaldi", "Application", "vivaldi.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Vivaldi", "Application", "vivaldi.exe"),
    ],
  },
  {
    key: "arc",
    name: "Arc",
    processName: "arc.exe",
    pathCandidates: [
      path.join(process.env.LOCALAPPDATA || "", "Programs", "Arc", "Arc.exe"),
    ],
  },
];

function parseArgs(argv) {
  const args = {
    taskFile: "",
    outputFile: "",
    prompt: "",
    promptContains: "",
    pageUrl: DEFAULT_PAGE_URL,
    profileDir: "",
    statePath: DEFAULT_STATE_PATH,
    browser: "",
    browserPath: "",
    port: DEFAULT_PORT,
    startTimeoutSec: 60,
    completeTimeoutSec: 300,
    pollIntervalMs: 1500,
    screenshotPath: "",
    detectBrowserOnly: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    switch (key) {
      case "--task-file":
        args.taskFile = value || "";
        index += 1;
        break;
      case "--output-file":
        args.outputFile = value || "";
        index += 1;
        break;
      case "--prompt":
        args.prompt = value || "";
        index += 1;
        break;
      case "--prompt-contains":
        args.promptContains = value || "";
        index += 1;
        break;
      case "--page-url":
        args.pageUrl = value || args.pageUrl;
        index += 1;
        break;
      case "--profile-dir":
        args.profileDir = value || args.profileDir;
        index += 1;
        break;
      case "--state-path":
        args.statePath = value || args.statePath;
        index += 1;
        break;
      case "--browser":
        args.browser = value || args.browser;
        index += 1;
        break;
      case "--browser-path":
        args.browserPath = value || args.browserPath;
        index += 1;
        break;
      case "--edge-path":
        args.browserPath = value || args.browserPath;
        index += 1;
        break;
      case "--port":
        args.port = Number.parseInt(value || `${DEFAULT_PORT}`, 10) || DEFAULT_PORT;
        index += 1;
        break;
      case "--start-timeout-sec":
        args.startTimeoutSec = Number.parseInt(value || "60", 10) || 60;
        index += 1;
        break;
      case "--complete-timeout-sec":
        args.completeTimeoutSec = Number.parseInt(value || "300", 10) || 300;
        index += 1;
        break;
      case "--poll-interval-ms":
        args.pollIntervalMs = Number.parseInt(value || "1500", 10) || 1500;
        index += 1;
        break;
      case "--screenshot-path":
        args.screenshotPath = value || "";
        index += 1;
        break;
      case "--detect-browser-only":
        args.detectBrowserOnly = true;
        break;
      default:
        break;
    }
  }

  return args;
}

function nowIso() {
  return new Date().toISOString();
}

function ensureParent(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function writeJson(filePath, payload) {
  if (!filePath) {
    return;
  }
  ensureParent(filePath);
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function readJson(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }
  const raw = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
  return JSON.parse(raw);
}

function normalizePathValue(filePath) {
  if (!filePath) {
    return "";
  }
  return path.normalize(String(filePath));
}

function samePath(left, right) {
  return normalizePathValue(left).toLowerCase() === normalizePathValue(right).toLowerCase();
}

function uniquePaths(paths) {
  const seen = new Set();
  const result = [];
  for (const candidate of paths || []) {
    const normalized = normalizePathValue(candidate);
    if (!normalized) {
      continue;
    }
    const key = normalized.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(normalized);
  }
  return result;
}

function normalizeBrowserKey(value) {
  return String(value || "").trim().toLowerCase();
}

function toSupportedCandidate(definition, filePath, source) {
  return {
    key: definition.key,
    name: definition.name,
    processName: definition.processName,
    path: normalizePathValue(filePath),
    source,
  };
}

function buildCustomBrowserCandidate(browserPath, source = "explicit_path", browserName = "") {
  const normalizedPath = normalizePathValue(browserPath);
  const definition = SUPPORTED_BROWSERS.find((candidate) => uniquePaths(candidate.pathCandidates).some((candidatePath) => samePath(candidatePath, normalizedPath)))
    || SUPPORTED_BROWSERS.find((candidate) => candidate.processName === path.basename(normalizedPath).toLowerCase());
  return {
    key: definition?.key || path.basename(normalizedPath, path.extname(normalizedPath)).toLowerCase() || "custom",
    name: browserName || definition?.name || path.basename(normalizedPath, path.extname(normalizedPath)) || "Custom Browser",
    processName: definition?.processName || path.basename(normalizedPath).toLowerCase(),
    path: normalizedPath,
    source,
  };
}

function getInstalledBrowserCandidates() {
  return SUPPORTED_BROWSERS
    .map((definition) => {
      const matchedPath = uniquePaths(definition.pathCandidates).find((candidate) => fs.existsSync(candidate));
      if (!matchedPath) {
        return null;
      }
      return toSupportedCandidate(definition, matchedPath, "installed");
    })
    .filter(Boolean);
}

function readStatePayload(statePath) {
  const payload = readJson(statePath);
  return payload && typeof payload === "object" ? payload : {};
}

function resolveBrowserSelection(args, statePayload) {
  const explicitBrowserPath = normalizePathValue(args.browserPath);
  if (explicitBrowserPath) {
    if (!fs.existsSync(explicitBrowserPath)) {
      throw new Error(`Configured browser executable was not found: ${explicitBrowserPath}`);
    }
    return buildCustomBrowserCandidate(explicitBrowserPath, "explicit_path");
  }

  const explicitBrowserKey = normalizeBrowserKey(args.browser || "");
  const preferredBrowserKey = normalizeBrowserKey(args.browser || statePayload.browser_key || "");
  const stateBrowserPath = normalizePathValue(statePayload.browser_path || "");
  if (stateBrowserPath && fs.existsSync(stateBrowserPath)) {
    const stateBrowserKey = normalizeBrowserKey(statePayload.browser_key || "");
    if (!preferredBrowserKey || !stateBrowserKey || stateBrowserKey === preferredBrowserKey) {
      return buildCustomBrowserCandidate(stateBrowserPath, "state_reuse", String(statePayload.browser_name || ""));
    }
  }

  const installedCandidates = getInstalledBrowserCandidates();
  if (preferredBrowserKey) {
    const preferredCandidate = installedCandidates.find((candidate) => candidate.key === preferredBrowserKey);
    if (preferredCandidate) {
      return {
        ...preferredCandidate,
        source: statePayload.browser_key ? "state_key_preferred" : "preferred_browser",
      };
    }
    if (explicitBrowserKey) {
      throw new Error(`Requested browser is not installed: ${explicitBrowserKey}`);
    }
  }

  if (installedCandidates.length > 0) {
    return {
      ...installedCandidates[0],
      source: "installed_default",
    };
  }

  const supportedNames = SUPPORTED_BROWSERS.map((candidate) => candidate.name).join(" / ");
  const error = new Error(`No supported Chromium browser was found. Supported browsers: ${supportedNames}. Install Edge and retry.`);
  error.code = "no_supported_browser_found";
  throw error;
}

function resolveProfileDir(args, statePayload, browser) {
  if (args.profileDir) {
    return normalizePathValue(args.profileDir);
  }

  const stateProfileDir = normalizePathValue(statePayload.profile_dir || "");
  const stateBrowserPath = normalizePathValue(statePayload.browser_path || "");
  const stateBrowserKey = normalizeBrowserKey(statePayload.browser_key || "");
  if (
    stateProfileDir
    && (
      (stateBrowserPath && samePath(stateBrowserPath, browser.path))
      || (stateBrowserKey && stateBrowserKey === browser.key)
      || (!stateBrowserKey && browser.key === "edge" && path.basename(stateProfileDir).toLowerCase() === "edge-profile")
    )
  ) {
    return stateProfileDir;
  }

  if (browser.key === "edge" && fs.existsSync(LEGACY_EDGE_PROFILE_DIR)) {
    return LEGACY_EDGE_PROFILE_DIR;
  }

  return path.join(PROFILES_ROOT, browser.key || "custom");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizePromptNeedle(prompt, explicitNeedle) {
  const raw = (explicitNeedle || prompt || "").replace(/\s+/g, " ").trim();
  if (!raw) {
    return "";
  }
  return raw.length > 96 ? raw.slice(0, 96).trim() : raw;
}

function hasCjk(text) {
  return /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]/u.test(String(text || ""));
}

function isEnglishPromptText(text) {
  const value = String(text || "").trim();
  if (!value) {
    return false;
  }
  if (hasCjk(value)) {
    return false;
  }
  return /[A-Za-z]/.test(value);
}

function normalizeMatchPath(pathname) {
  const value = String(pathname || "").trim();
  if (!value) {
    return "/";
  }
  const normalized = value.replace(/\/+$/g, "");
  return normalized || "/";
}

function scoreTargetUrlMatch(targetUrl, expectedUrl) {
  const current = String(targetUrl || "").trim();
  const expected = String(expectedUrl || "").trim();
  if (!current || !expected) {
    return 0;
  }
  if (current === expected) {
    return 5;
  }
  if (
    current.startsWith(`${expected}?`)
    || current.startsWith(`${expected}#`)
    || current.startsWith(`${expected}/`)
  ) {
    return 4;
  }
  try {
    const expectedParsed = new URL(expected);
    const currentParsed = new URL(current);
    if (expectedParsed.origin !== currentParsed.origin) {
      return 0;
    }
    if (normalizeMatchPath(expectedParsed.pathname) === normalizeMatchPath(currentParsed.pathname)) {
      return 3;
    }
    return 1;
  } catch {
    return 0;
  }
}

function matchesExpectedPageUrl(targetUrl, expectedUrl) {
  return scoreTargetUrlMatch(targetUrl, expectedUrl) >= 3;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${url}`);
  }
  return response.json();
}

async function tryFetchJson(url, options = {}) {
  try {
    return await fetchJson(url, options);
  } catch {
    return null;
  }
}

class CdpClient {
  constructor(webSocketUrl) {
    this.webSocketUrl = webSocketUrl;
    this.ws = null;
    this.sequence = 0;
    this.pending = new Map();
  }

  async connect() {
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(this.webSocketUrl);
      this.ws = ws;
      ws.addEventListener("open", () => resolve());
      ws.addEventListener("error", (event) => reject(event.error || new Error("WebSocket 连接失败")));
      ws.addEventListener("message", (event) => {
        const message = JSON.parse(event.data.toString());
        if (!Object.prototype.hasOwnProperty.call(message, "id")) {
          return;
        }
        const pending = this.pending.get(message.id);
        if (!pending) {
          return;
        }
        this.pending.delete(message.id);
        if (message.error) {
          pending.reject(new Error(message.error.message || "CDP 调用失败"));
          return;
        }
        pending.resolve(message.result || {});
      });
      ws.addEventListener("close", () => {
        for (const [, pending] of this.pending) {
          pending.reject(new Error("CDP 连接已关闭"));
        }
        this.pending.clear();
      });
    });
  }

  call(method, params = {}) {
    const id = ++this.sequence;
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(payload);
    });
  }

  async close() {
    if (!this.ws) {
      return;
    }
    await new Promise((resolve) => {
      this.ws.addEventListener("close", () => resolve(), { once: true });
      this.ws.close();
    });
  }
}

function buildPageInspectionExpression() {
  return `(() => {
    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
    const title = normalize(document.title || "");
    const url = String(location.href || "");
    const bodyText = normalize(document.body ? document.body.innerText : "");
    const visible = (element) => {
      if (!element) return false;
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const editable = (element) => {
      if (!visible(element)) return false;
      if (element.matches("textarea,input")) {
        if (element.disabled || element.readOnly) return false;
        return true;
      }
      return Boolean(element.isContentEditable);
    };
    const controls = Array.from(document.querySelectorAll("button,a"));
    const loginHints = controls.some((element) => /log in|sign in|continue with google|continue with discord|登录|继续使用/i.test(normalize(element.innerText) + " " + normalize(element.getAttribute("aria-label"))));
    const challenge = /just a moment|enable javascript and cookies to continue|请稍候/i.test(title + " " + bodyText);
    const candidates = Array.from(document.querySelectorAll('textarea,[contenteditable="true"],input[type="text"],input:not([type])'))
      .filter(editable)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const label = normalize(element.getAttribute("placeholder")) + " " + normalize(element.getAttribute("aria-label")) + " " + normalize(element.innerText);
        let score = rect.width * rect.height;
        if (/imagine|prompt|what will you imagine/i.test(label)) score += 200000;
        if (element.tagName === "TEXTAREA") score += 50000;
        if (element.isContentEditable) score += 30000;
        if (rect.top >= 0 && rect.top <= 260) score += 20000;
        return {
          tagName: element.tagName,
          isContentEditable: Boolean(element.isContentEditable),
          label,
          rect: {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            centerX: rect.x + rect.width / 2,
            centerY: rect.y + rect.height / 2
          },
          score
        };
      })
      .sort((left, right) => right.score - left.score);
    return {
      title,
      url,
      challenge,
      loginHints,
      inputReady: candidates.length > 0,
      inputCandidate: candidates.length > 0 ? candidates[0] : null,
      bodySample: bodyText.slice(0, 800)
    };
  })()`;
}

function buildClearInputExpression() {
  return `(() => {
    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
    const visible = (element) => {
      if (!element) return false;
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const editable = (element) => {
      if (!visible(element)) return false;
      if (element.matches("textarea,input")) {
        if (element.disabled || element.readOnly) return false;
        return true;
      }
      return Boolean(element.isContentEditable);
    };
    const candidates = Array.from(document.querySelectorAll('textarea,[contenteditable="true"],input[type="text"],input:not([type])'))
      .filter(editable)
      .sort((left, right) => {
        const leftRect = left.getBoundingClientRect();
        const rightRect = right.getBoundingClientRect();
        const leftScore = leftRect.width * leftRect.height + (/imagine|prompt|what will you imagine/i.test(normalize(left.getAttribute("placeholder")) + " " + normalize(left.getAttribute("aria-label")) + " " + normalize(left.innerText)) ? 100000 : 0);
        const rightScore = rightRect.width * rightRect.height + (/imagine|prompt|what will you imagine/i.test(normalize(right.getAttribute("placeholder")) + " " + normalize(right.getAttribute("aria-label")) + " " + normalize(right.innerText)) ? 100000 : 0);
        return rightScore - leftScore;
      });
    const element = candidates[0];
    if (!element) {
      return { ok: false };
    }
    element.focus();
    if ('value' in element) {
      const proto = Object.getPrototypeOf(element);
      const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
      if (descriptor && descriptor.set) {
        descriptor.set.call(element, '');
      } else {
        element.value = '';
      }
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      return { ok: true, mode: 'value' };
    }
    if (element.isContentEditable) {
      element.innerHTML = '';
      element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
      return { ok: true, mode: 'contenteditable' };
    }
    return { ok: false };
  })()`;
}

function buildStatusExpression(promptNeedle) {
  return `(() => {
    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
    const visible = (element) => {
      if (!element) return false;
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const rectData = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height
      };
    };
    const buildKey = (rect, promptText) => {
      return [
        Math.round(rect.left / 12),
        Math.round(rect.top / 12),
        Math.round(rect.width / 12),
        Math.round(rect.height / 12),
        normalize(promptText).toLowerCase().slice(0, 80)
      ].join(":");
    };
    const imageCountFor = (element) => {
      const imgCount = Array.from(element.querySelectorAll("img")).filter((img) => {
        const rect = img.getBoundingClientRect();
        return rect.width >= 32 && rect.height >= 32;
      }).length;
      const bgCount = Array.from(element.querySelectorAll("*")).filter((node) => {
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return rect.width >= 48 && rect.height >= 48 && style.backgroundImage && style.backgroundImage !== "none";
      }).length;
      return imgCount + bgCount;
    };
    const findPromptText = (element, needle) => {
      const lines = normalize(element.innerText || "").split(/\\n+/).map((line) => normalize(line)).filter(Boolean);
      const found = lines.find((line) => line.toLowerCase().includes(needle));
      return found || normalize(element.innerText || "").slice(0, 240);
    };
    const pickRegionContainer = (element, needle) => {
      let current = element;
      let best = null;
      let bestArea = Number.POSITIVE_INFINITY;
      while (current) {
        if (visible(current)) {
          const rect = current.getBoundingClientRect();
          const text = normalize(current.innerText || "");
          const area = rect.width * rect.height;
          if (
            rect.width >= 220 &&
            rect.height >= 80 &&
            rect.width <= 1600 &&
            rect.height <= 1200 &&
            text.toLowerCase().includes(needle)
          ) {
            if (area < bestArea) {
              best = current;
              bestArea = area;
            }
          }
        }
        current = current.parentElement;
      }
      return best || element;
    };
    const text = normalize(document.body ? document.body.innerText : "");
    const lower = text.toLowerCase();
    const needle = ${JSON.stringify(promptNeedle.toLowerCase())};
    const progressPattern = /(Submitting\\.\\.\\.|Starting\\.\\.\\.|[0-9]{1,3}% Complete)/g;
    const regionMap = new Map();
    if (needle) {
      const promptNodes = Array.from(document.querySelectorAll("article, section, li, div, p, span"))
        .filter((element) => visible(element))
        .filter((element) => normalize(element.innerText || "").toLowerCase().includes(needle));
      for (const promptNode of promptNodes) {
        const region = pickRegionContainer(promptNode, needle);
        if (!visible(region)) continue;
        const regionText = normalize(region.innerText || "");
        if (!regionText.toLowerCase().includes(needle)) continue;
        const progressMatches = regionText.match(progressPattern) || [];
        const promptText = findPromptText(region, needle);
        const bounds = rectData(region);
        const imageCount = imageCountFor(region);
        const key = buildKey(bounds, promptText);
        let regionState = "submitting";
        if (progressMatches.length > 0) {
          regionState = "generating";
        } else if (imageCount > 0) {
          regionState = "completed";
        }
        const candidate = {
          region_key: key,
          prompt_text: promptText,
          region_state: regionState,
          region_progress_text: progressMatches[0] || "",
          region_progress_matches: progressMatches.slice(0, 6),
          region_image_count: imageCount,
          region_has_placeholder: imageCount === 0,
          region_bounds: bounds,
          score: Math.round(bounds.width * bounds.height) + imageCount * 10000 + progressMatches.length * 5000
        };
        const existing = regionMap.get(key);
        if (!existing || candidate.score > existing.score) {
          regionMap.set(key, candidate);
        }
      }
    }
    const regions = Array.from(regionMap.values()).sort((left, right) => {
      if (left.region_bounds.top !== right.region_bounds.top) {
        return left.region_bounds.top - right.region_bounds.top;
      }
      return right.score - left.score;
    });
    const firstRegion = regions[0] || null;
    const progressMatches = regions.flatMap((region) => region.region_progress_matches || []).slice(0, 12);
    const status = firstRegion ? firstRegion.region_state : "not_found";
    return {
      status,
      prompt_found: regions.length > 0,
      prompt_region_found: regions.length > 0,
      generating_signal_found: progressMatches.length > 0,
      matched_prompt_count: regions.length,
      matched_progress_count: progressMatches.length,
      max_prompt_index: regions.length > 0 ? 0 : -1,
      progress_matches: progressMatches.slice(0, 12),
      region_keys: regions.map((region) => region.region_key),
      regions,
      title: normalize(document.title || ""),
      url: String(location.href || "")
    };
  })()`;
}

function regionStatePriority(region) {
  if (!region || !region.region_state) {
    return 99;
  }
  if (region.region_state === "generating") {
    return 0;
  }
  if (region.region_state === "submitting") {
    return 1;
  }
  if (region.region_state === "completed") {
    return 2;
  }
  return 99;
}

function getRegionArea(region) {
  const width = Number(region?.region_bounds?.width || 0);
  const height = Number(region?.region_bounds?.height || 0);
  return Math.max(0, width) * Math.max(0, height);
}

function getRegionCenter(region) {
  const bounds = region?.region_bounds || {};
  const left = Number(bounds.left || 0);
  const top = Number(bounds.top || 0);
  const width = Number(bounds.width || 0);
  const height = Number(bounds.height || 0);
  return {
    x: left + (width / 2),
    y: top + (height / 2),
  };
}

function scoreRegionAffinity(region, referenceRegion, baselineKeys) {
  if (!region || !referenceRegion) {
    return Number.POSITIVE_INFINITY;
  }
  const candidateArea = getRegionArea(region);
  const referenceArea = Math.max(1, getRegionArea(referenceRegion));
  const areaRatio = candidateArea > 0
    ? Math.max(candidateArea / referenceArea, referenceArea / candidateArea)
    : Number.POSITIVE_INFINITY;
  const candidateCenter = getRegionCenter(region);
  const referenceCenter = getRegionCenter(referenceRegion);
  const distance = Math.hypot(candidateCenter.x - referenceCenter.x, candidateCenter.y - referenceCenter.y);
  const baselinePenalty = baselineKeys.has(region.region_key) ? 20000 : 0;
  const oversizedPenalty = areaRatio > 6 ? 10000 : 0;
  const imageReward = Math.min(20, Number(region.region_image_count || 0)) * 10;
  return baselinePenalty + oversizedPenalty + distance + (Math.abs(Math.log(areaRatio || 1)) * 1000) - imageReward;
}

function selectTargetRegion(probe, baselineKeys, lockedRegionKey, previousTargetRegion = null) {
  const regions = Array.isArray(probe?.regions) ? probe.regions : [];
  const probeStatus = String(probe?.status || "");
  const sortRegions = (items) => items
    .slice()
    .sort((left, right) => {
      const stateOrder = regionStatePriority(left) - regionStatePriority(right);
      if (stateOrder !== 0) return stateOrder;
      if ((left.region_bounds?.top || 0) !== (right.region_bounds?.top || 0)) {
        return (left.region_bounds?.top || 0) - (right.region_bounds?.top || 0);
      }
      return (right.score || 0) - (left.score || 0);
    });

  if (lockedRegionKey) {
    const lockedRegion = regions.find((region) => region.region_key === lockedRegionKey);
    if (lockedRegion) {
      return lockedRegion;
    }
    if (probeStatus === "completed") {
      const completedCandidates = regions.filter(
        (region) => region.region_state === "completed" && Number(region.region_image_count || 0) > 0
      );
      if (previousTargetRegion) {
        const completionMatch = completedCandidates
          .slice()
          .sort((left, right) => {
            const affinityOrder = scoreRegionAffinity(left, previousTargetRegion, baselineKeys)
              - scoreRegionAffinity(right, previousTargetRegion, baselineKeys);
            if (affinityOrder !== 0) {
              return affinityOrder;
            }
            return sortRegions([left, right])[0] === left ? -1 : 1;
          });
        if (completionMatch.length > 0) {
          return completionMatch[0];
        }
      }
      const completedRegions = sortRegions(completedCandidates);
      if (completedRegions.length > 0) {
        return completedRegions[0];
      }
    }
  }
  const newRegions = sortRegions(
    regions
    .filter((region) => !baselineKeys.has(region.region_key))
  );
  if (newRegions.length > 0) {
    return newRegions[0];
  }

  if (baselineKeys.size === 0) {
    const fallbackRegions = sortRegions(regions);
    if (fallbackRegions.length > 0) {
      return fallbackRegions[0];
    }
  }
  return null;
}

function isTargetRegionCompleted(region) {
  return Boolean(region && region.region_state === "completed" && Number(region.region_image_count || 0) > 0);
}

async function evaluateValue(cdp, expression) {
  const result = await cdp.call("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
    userGesture: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "页面脚本执行失败");
  }
  return result.result ? result.result.value : null;
}

async function waitForReadyState(cdp, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const ready = await evaluateValue(cdp, "document.readyState");
    if (ready === "complete" || ready === "interactive") {
      return ready;
    }
    await delay(500);
  }
  throw new Error("页面加载超时");
}

async function waitForInteractiveInspection(cdp, expectedUrl, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastInspection = null;
  while (Date.now() < deadline) {
    const inspection = await evaluateValue(cdp, buildPageInspectionExpression());
    lastInspection = inspection;
    if (inspection?.challenge || inspection?.loginHints || inspection?.inputReady) {
      return inspection;
    }
    if (matchesExpectedPageUrl(inspection?.url, expectedUrl)) {
      await delay(500);
      continue;
    }
    if (String(inspection?.url || "").trim() === "about:blank") {
      await delay(500);
      continue;
    }
    await delay(500);
  }
  return lastInspection;
}

async function ensureDebugBrowser(args, statePayload) {
  const selectedBrowser = resolveBrowserSelection(args, statePayload);
  args.profileDir = resolveProfileDir(args, statePayload, selectedBrowser);
  fs.mkdirSync(args.profileDir, { recursive: true });
  let version = await tryFetchJson(`http://127.0.0.1:${args.port}/json/version`);
  let launched = false;
  if (!version) {
    const child = spawn(selectedBrowser.path, [
      `--remote-debugging-port=${args.port}`,
      `--user-data-dir=${args.profileDir}`,
      "--new-window",
      args.pageUrl,
    ], {
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    child.unref();
    launched = true;
    const deadline = Date.now() + args.startTimeoutSec * 1000;
    while (Date.now() < deadline) {
      await delay(500);
      version = await tryFetchJson(`http://127.0.0.1:${args.port}/json/version`);
      if (version) {
        break;
      }
    }
  }

  if (!version) {
    throw new Error("独立浏览器调试端口未启动");
  }

  writeJson(args.statePath, {
    profile_dir: args.profileDir,
    port: args.port,
    browser_key: selectedBrowser.key,
    browser_name: selectedBrowser.name,
    browser_path: selectedBrowser.path,
    browser_process_name: selectedBrowser.processName,
    browser_detection_source: selectedBrowser.source,
    browser: version.Browser || "",
    web_socket_debugger_url: version.webSocketDebuggerUrl || "",
    page_url: args.pageUrl,
    last_seen_at: nowIso(),
    updated_at: nowIso(),
  });

  return {
    version,
    launched,
    selectedBrowser,
    profileDir: args.profileDir,
  };
}

async function getOrCreateMidjourneyTarget(args) {
  const pickBestTarget = (targets) => targets
    .filter((target) => target.type === "page")
    .map((target) => ({
      ...target,
      __matchScore: scoreTargetUrlMatch(target.url, args.pageUrl),
    }))
    .filter((target) => target.__matchScore >= 3)
    .sort((left, right) => right.__matchScore - left.__matchScore)[0] || null;

  let targets = await fetchJson(`http://127.0.0.1:${args.port}/json/list`);
  let pageTarget = pickBestTarget(targets);
  if (!pageTarget) {
    await fetchJson(`http://127.0.0.1:${args.port}/json/new?${encodeURIComponent(args.pageUrl)}`, { method: "PUT" });
    await delay(1000);
    targets = await fetchJson(`http://127.0.0.1:${args.port}/json/list`);
    pageTarget = pickBestTarget(targets);
  }
  if (!pageTarget) {
    throw new Error("未找到 Midjourney 目标页");
  }
  return {
    pageTarget,
    targets,
  };
}

async function captureScreenshot(cdp, screenshotPath, clipRect = null) {
  const options = { format: "png", fromSurface: true };
  if (clipRect && clipRect.width > 0 && clipRect.height > 0) {
    options.clip = {
      x: clipRect.left,
      y: clipRect.top,
      width: clipRect.width,
      height: clipRect.height,
      scale: 1,
    };
  }
  const result = await cdp.call("Page.captureScreenshot", options);
  const targetPath = screenshotPath || path.join(os.tmpdir(), `midjourney-isolated-${Date.now()}.png`);
  fs.writeFileSync(targetPath, Buffer.from(result.data, "base64"));
  return {
    output_path: targetPath,
    clip_bounds: clipRect || null,
  };
}

async function clearInput(cdp) {
  await evaluateValue(cdp, buildClearInputExpression());
}

async function submitPrompt(cdp, inspection, prompt) {
  const point = inspection.inputCandidate.rect;
  await cdp.call("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: point.centerX,
    y: point.centerY,
    button: "left",
    buttons: 1,
  });
  await cdp.call("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: point.centerX,
    y: point.centerY,
    button: "left",
    buttons: 1,
    clickCount: 1,
  });
  await cdp.call("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: point.centerX,
    y: point.centerY,
    button: "left",
    buttons: 1,
    clickCount: 1,
  });
  await clearInput(cdp);
  await cdp.call("Input.insertText", { text: prompt });
  await cdp.call("Input.dispatchKeyEvent", {
    type: "keyDown",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
    key: "Enter",
    code: "Enter",
    text: "\r",
    unmodifiedText: "\r",
  });
  await cdp.call("Input.dispatchKeyEvent", {
    type: "keyUp",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
    key: "Enter",
    code: "Enter",
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const statePayload = readStatePayload(args.statePath);
  if (args.detectBrowserOnly) {
    const selectedBrowser = resolveBrowserSelection(args, statePayload);
    const profileDir = resolveProfileDir(args, statePayload, selectedBrowser);
    const result = {
      ok: true,
      browser_detection_only: true,
      browser_key: selectedBrowser.key,
      browser_name: selectedBrowser.name,
      browser_path: selectedBrowser.path,
      browser_process_name: selectedBrowser.processName,
      browser_detection_source: selectedBrowser.source,
      profile_dir: profileDir,
      state_path: args.statePath,
    };
    writeJson(args.outputFile, result);
    console.log(JSON.stringify(result, null, 2));
    return;
  }
  const task = readJson(args.taskFile) || {};
  const promptFromPackage = String(task.prompt_package?.prompt_text || "").trim();
  const promptSource = args.prompt
    ? "cli_argument"
    : promptFromPackage
      ? "prompt_package"
      : String(task.current_prompt || "").trim()
        ? "current_prompt"
        : "";
  const prompt = args.prompt || promptFromPackage || String(task.current_prompt || "").trim();
  const promptNeedle = normalizePromptNeedle(prompt, args.promptContains || String(task.artifacts?.prompt_contains || ""));

  if (!prompt) {
    throw new Error("缺少 prompt");
  }
  if (!promptNeedle) {
    throw new Error("缺少 prompt 命中串");
  }

  const metadata = {
    task_id: String(task.task_id || ""),
    project_id: String(task.project_id || ""),
    mode: String(task.mode || ""),
    round_index: Number.parseInt(`${task.round_index || 0}`, 10) || 0,
    task_phase: String(task.task_phase || ""),
    automatic_execution_backend: "isolated_browser",
    prompt_source: promptSource,
  };

  if (!isEnglishPromptText(prompt)) {
    const result = {
      ...metadata,
      ok: false,
      blocked_by_context: true,
      blocked_reason: "english_prompt_required",
      result_available: false,
      started_generating: false,
      completed: false,
      probe_needle: promptNeedle,
      browser_backend: "isolated_cdp_v2",
    };
    writeJson(args.outputFile, result);
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  const browser = await ensureDebugBrowser(args, statePayload);
  const browserMetadata = {
    browser_key: browser.selectedBrowser.key,
    browser_name: browser.selectedBrowser.name,
    browser_path: browser.selectedBrowser.path,
    browser_process_name: browser.selectedBrowser.processName,
    browser_detection_source: browser.selectedBrowser.source,
    browser_version: browser.version.Browser || "",
    browser_launched: browser.launched,
    profile_dir: browser.profileDir,
  };
  const targetInfo = await getOrCreateMidjourneyTarget(args);
  const cdp = new CdpClient(targetInfo.pageTarget.webSocketDebuggerUrl);
  await cdp.connect();

  try {
    await cdp.call("Page.enable");
    await cdp.call("Runtime.enable");
    const currentUrl = await evaluateValue(cdp, "String(location.href || '')");
    if (!matchesExpectedPageUrl(currentUrl, args.pageUrl)) {
      await cdp.call("Page.navigate", { url: args.pageUrl });
    }
    await waitForReadyState(cdp);
    const inspection = await waitForInteractiveInspection(
      cdp,
      args.pageUrl,
      Math.max(5000, Math.min(args.startTimeoutSec * 1000, 30000)),
    );
    if (inspection.challenge) {
      const result = {
        ...metadata,
        ...browserMetadata,
        ok: false,
        blocked_by_ui: true,
        blocked_reason: "isolated_browser_challenge_page",
        result_available: false,
        started_generating: false,
        completed: false,
        probe_needle: promptNeedle,
        browser_backend: "isolated_cdp_v2",
        page_state: inspection,
        debug_target: {
          url: targetInfo.pageTarget.url,
          title: targetInfo.pageTarget.title,
          id: targetInfo.pageTarget.id,
        },
      };
      writeJson(args.outputFile, result);
      console.log(JSON.stringify(result, null, 2));
      return;
    }

    if (!inspection.inputReady) {
      const blockedReason = inspection.loginHints ? "needs_isolated_browser_login" : "isolated_browser_input_not_ready";
      const result = {
        ...metadata,
        ...browserMetadata,
        ok: false,
        blocked_by_ui: true,
        blocked_reason: blockedReason,
        result_available: false,
        started_generating: false,
        completed: false,
        probe_needle: promptNeedle,
        browser_backend: "isolated_cdp_v2",
        page_state: inspection,
        debug_target: {
          url: targetInfo.pageTarget.url,
          title: targetInfo.pageTarget.title,
          id: targetInfo.pageTarget.id,
        },
      };
      writeJson(args.outputFile, result);
      console.log(JSON.stringify(result, null, 2));
      return;
    }

    const baselineProbe = await evaluateValue(cdp, buildStatusExpression(promptNeedle));
    const baselineRegionKeys = new Set(Array.isArray(baselineProbe?.region_keys) ? baselineProbe.region_keys : []);
    await submitPrompt(cdp, inspection, prompt);

    const startDeadline = Date.now() + args.startTimeoutSec * 1000;
    const completeDeadline = Date.now() + args.completeTimeoutSec * 1000;
    const statusTransitions = [];
    const probeTimeline = [];
    const pushStatus = (status) => {
      if (!status) return;
      if (statusTransitions.length === 0 || statusTransitions.at(-1) !== status) {
        statusTransitions.push(status);
      }
    };
    const pushProbe = (probe) => {
      probeTimeline.push({
        at: nowIso(),
        status: probe.status,
        matched_prompt_count: probe.matched_prompt_count,
        matched_progress_count: probe.matched_progress_count,
        max_prompt_index: probe.max_prompt_index,
        target_region_key: probe.target_region_key || "",
        target_region_state: probe.target_region_state || "",
        target_region_image_count: Number(probe.target_region_image_count || 0),
      });
      pushStatus(probe.target_region_state || probe.status);
    };

    pushProbe(baselineProbe);

    let startProbe = null;
    let completeProbe = null;
    let startedGenerating = false;
    let completed = false;
    let blockedReason = "";
    let lockedRegionKey = "";
    let finalTargetRegion = null;

    while (Date.now() < startDeadline) {
      await delay(args.pollIntervalMs);
      const probe = await evaluateValue(cdp, buildStatusExpression(promptNeedle));
      const targetRegion = selectTargetRegion(probe, baselineRegionKeys, lockedRegionKey, finalTargetRegion);
      if (targetRegion && targetRegion.region_key !== lockedRegionKey) {
        lockedRegionKey = targetRegion.region_key;
      }
      if (targetRegion) {
        finalTargetRegion = targetRegion;
      }
      probe.target_region_key = targetRegion ? targetRegion.region_key : "";
      probe.target_region_state = targetRegion ? targetRegion.region_state : "";
      probe.target_region_image_count = targetRegion ? Number(targetRegion.region_image_count || 0) : 0;
      pushProbe(probe);
      if (!startProbe && targetRegion) {
        startProbe = probe;
      }
      if (targetRegion && targetRegion.region_state === "generating") {
        startedGenerating = true;
        break;
      }
      if (targetRegion && isTargetRegionCompleted(targetRegion) && startProbe) {
        completed = true;
        completeProbe = probe;
        break;
      }
    }

    if (!startedGenerating && !completed) {
      blockedReason = "start_timeout";
    }

    while (!completed && !blockedReason && Date.now() < completeDeadline) {
      await delay(args.pollIntervalMs);
      const probe = await evaluateValue(cdp, buildStatusExpression(promptNeedle));
      const targetRegion = selectTargetRegion(probe, baselineRegionKeys, lockedRegionKey, finalTargetRegion);
      if (targetRegion && targetRegion.region_key !== lockedRegionKey) {
        lockedRegionKey = targetRegion.region_key;
      }
      if (targetRegion) {
        finalTargetRegion = targetRegion;
      }
      probe.target_region_key = targetRegion ? targetRegion.region_key : "";
      probe.target_region_state = targetRegion ? targetRegion.region_state : "";
      probe.target_region_image_count = targetRegion ? Number(targetRegion.region_image_count || 0) : 0;
      pushProbe(probe);
      if (!startProbe && targetRegion) {
        startProbe = probe;
      }
      if (targetRegion && targetRegion.region_state === "generating") {
        startedGenerating = true;
        continue;
      }
      if (targetRegion && isTargetRegionCompleted(targetRegion) && (lockedRegionKey || startProbe)) {
        completed = true;
        completeProbe = probe;
        break;
      }
    }

    if (!completed && !blockedReason) {
      blockedReason = "complete_timeout";
    }

    let finalCapture = null;
    if (completed) {
      const clipRect = finalTargetRegion?.region_bounds || null;
      finalCapture = await captureScreenshot(cdp, args.screenshotPath, clipRect);
    }

    const result = {
      ...metadata,
      ...browserMetadata,
      ok: completed && !blockedReason,
      blocked_by_ui: !completed,
      blocked_reason: blockedReason,
      formal_flow_version: "isolated_prompt_region_v2",
      browser_backend: "isolated_cdp_v2",
      probe_needle: promptNeedle,
      result_available: completed,
      should_continue: false,
      started_generating: Boolean(startProbe),
      generation_observed: startedGenerating,
      completed,
      baseline_region_keys: Array.from(baselineRegionKeys),
      target_region_key: lockedRegionKey,
      target_region: finalTargetRegion,
      page_state: inspection,
      baseline_probe: baselineProbe,
      start_probe: startProbe,
      complete_probe: completeProbe,
      status_transitions: statusTransitions,
      probe_timeline: probeTimeline,
      final_capture: finalCapture,
      debug_target: {
        url: targetInfo.pageTarget.url,
        title: targetInfo.pageTarget.title,
        id: targetInfo.pageTarget.id,
      },
      isolated_browser: {
        profile_dir: args.profileDir,
        port: args.port,
        state_path: args.statePath,
        browser_key: browser.selectedBrowser.key,
        browser_name: browser.selectedBrowser.name,
        browser_path: browser.selectedBrowser.path,
      },
    };
    writeJson(args.outputFile, result);
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await cdp.close();
  }
}

main().catch((error) => {
  const errorText = String(error && error.stack ? error.stack : error);
  let blockedReason = "isolated_browser_runtime_error";
  let blockedByUi = true;
  let blockedByContext = false;
  if (error && error.code === "no_supported_browser_found") {
    blockedReason = "no_supported_browser_found";
    blockedByUi = false;
    blockedByContext = true;
  } else if (errorText.includes("Chromium")) {
    blockedReason = "no_supported_browser_found";
    blockedByUi = false;
    blockedByContext = true;
  }
  const result = {
    ok: false,
    blocked_by_ui: blockedByUi,
    blocked_by_context: blockedByContext,
    blocked_reason: blockedReason,
    error: errorText,
    browser_backend: "isolated_cdp_v2",
  };
  const args = parseArgs(process.argv.slice(2));
  writeJson(args.outputFile, result);
  console.log(JSON.stringify(result, null, 2));
  process.exitCode = 1;
});
