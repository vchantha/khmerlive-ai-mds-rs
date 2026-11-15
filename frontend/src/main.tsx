import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Status =
  | "queued"
  | "processing"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed"
  | "dispatch_failed";
type Job = {
  id: string;
  filename: string;
  size_bytes: number;
  source_kind?: "upload" | "url";
  capture_seconds?: number | null;
  status: Status;
  progress: number;
  stage: string | null;
  source_lang: string;
  target_lang: string;
  created_at: string | null;
  error: string | null;
  has_output: boolean;
  has_subtitles?: boolean;
  has_khmer_voice?: boolean;
  processing_mode?: "demo" | "real_subtitles";
  cancel_requested: boolean;
  transcript: string | null;
  translation: string | null;
};
type Metrics = {
  total: number;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
};
type QueueData = { items: Job[]; total: number };
type SystemData = { services: Record<string, string> };
type Page =
  | "dashboard"
  | "new"
  | "queue"
  | "library"
  | "results"
  | "models"
  | "system"
  | "users";
type Account = {
  authenticated: boolean;
  user: {
    id: string;
    name: string;
    email: string | null;
    avatar_url: string | null;
  } | null;
  identities: { provider: string; display_name: string | null }[];
};
type Provider = { id: string; name: string; enabled: boolean };
type DirectoryUser = {
  id: string;
  display_name: string;
  email: string | null;
  created_at: string | null;
  providers: string[];
};
const empty: Metrics = {
  total: 0,
  queued: 0,
  processing: 0,
  completed: 0,
  failed: 0,
};
type IconName =
  | "dashboard"
  | "plus"
  | "jobs"
  | "library"
  | "result"
  | "models"
  | "users"
  | "system"
  | "key"
  | "docs"
  | "menu"
  | "upload"
  | "link"
  | "clock";

const iconPaths: Record<IconName, React.ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
  plus: <><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></>,
  jobs: <><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M8 11h8M8 15h5"/></>,
  library: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/></>,
  result: <><path d="M4 13.5 9 18l11-12"/><path d="M20 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9"/></>,
  models: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></>,
  users: <><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5.5a3 3 0 0 1 0 5.8M17 14a5 5 0 0 1 4 4.9V20"/></>,
  system: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
  key: <><circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M16 7l3 3M14 9l2 2"/></>,
  docs: <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
  upload: <><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 15v5h16v-5"/></>,
  link: <><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.2 1.2"/><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.2-1.2"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
};

function Icon({ name }: { name: IconName }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{iconPaths[name]}</svg>;
}

const workspacePages: [Page, IconName, string][] = [
  ["dashboard", "dashboard", "Dashboard"],
  ["new", "plus", "New Translation"],
  ["queue", "jobs", "My Jobs"],
  ["library", "library", "Video Library"],
  ["results", "result", "Video Results"],
];
const managePages: [Page, IconName, string][] = [
  ["models", "models", "AI Models"],
  ["users", "users", "Users & Access"],
  ["system", "system", "System Health"],
];

const pageCopy: Record<Page, [string, string]> = {
  dashboard: ["Dashboard", "Operational overview of video translation and dubbing."],
  new: ["New Translation", "Upload or capture a video and configure its language direction."],
  queue: ["My Jobs", "Track processing, review failures, and manage queued work."],
  library: ["Video Library", "Browse completed, downloadable video outputs."],
  results: ["Video Results", "Preview outputs, captions, transcripts, and translations."],
  models: ["AI Models", "Verify local model readiness before starting real inference."],
  users: ["Users & Access", "Manage sign-in methods and inspect authorized users."],
  system: ["System Health", "Monitor the services required by the processing pipeline."],
};
const limit = 6;
const asDate = (s: string | null) => (s ? new Date(s).toLocaleString() : "—");
const elapsed = (s: string | null) => {
  if (!s) return "—";
  const sec = Math.max(
    0,
    Math.floor((Date.now() - new Date(s).getTime()) / 1000),
  );
  return sec < 60
    ? "just now"
    : sec < 3600
      ? Math.floor(sec / 60) + " min ago"
      : sec < 86400
        ? Math.floor(sec / 3600) + " hr ago"
        : asDate(s);
};
const size = (n: number) =>
  n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.ceil(n / 1024) + " KB";
const finalStatus = (s: Status) => (s === "dispatch_failed" ? "failed" : s);
const label = (s: Status) =>
  s === "cancelling"
    ? "Cancelling"
    : s === "cancelled"
      ? "Cancelled"
      : s === "dispatch_failed"
        ? "Failed"
        : s.charAt(0).toUpperCase() + s.slice(1);
function Badge({ status }: { status: Status }) {
  return (
    <span
      className={"status-chip status-" + finalStatus(status)}
      aria-label={"Status " + label(status)}
    >
      <span aria-hidden="true">
        {status === "completed"
          ? "✓"
          : status === "failed" || status === "dispatch_failed"
            ? "!"
            : status === "queued"
              ? "◷"
              : status === "cancelled"
                ? "−"
                : "◌"}
      </span>
      {label(status)}
    </span>
  );
}
const downloadName = (n: string) =>
  n.replace(/\.mp4$/i, "") + "-translated.mp4";

function App() {
  const [key, setKey] = useState(
    sessionStorage.getItem("khmerlive_api_key") || "",
  );
  const [keyDraft, setKeyDraft] = useState(key),
    [keyModal, setKeyModal] = useState(false);
  const [account, setAccount] = useState<Account | null>(null),
    [providers, setProviders] = useState<Provider[]>([]);
  const [directory, setDirectory] = useState<DirectoryUser[]>([]),
    [directoryTotal, setDirectoryTotal] = useState(0);
  const [sidebarMode, setSidebarMode] = useState<
      "expanded" | "collapsed" | "hidden"
    >(() => {
      const saved = localStorage.getItem("khmerlive_sidebar_mode");
      return saved === "hidden" || saved === "collapsed" || saved === "expanded"
        ? saved
        : localStorage.getItem("khmerlive_sidebar_collapsed") === "true"
          ? "collapsed"
          : "expanded";
    }),
    [mobileNav, setMobileNav] = useState(false);
  const [isMobile, setIsMobile] = useState(() =>
    window.matchMedia("(max-width: 760px)").matches,
  );
  const collapsed = sidebarMode === "collapsed";
  const hidden = sidebarMode === "hidden";
  const [page, setPage] = useState<Page>("dashboard"),
    [file, setFile] = useState<File | null>(null),
    [language, setLanguage] = useState("en"),
    [busy, setBusy] = useState(false),
    [uploadPct, setUploadPct] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<Metrics>(empty),
    [queue, setQueue] = useState<Job[]>([]),
    [services, setServices] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Job | null>(null),
    [filter, setFilter] = useState("all"),
    [offset, setOffset] = useState(0),
    [total, setTotal] = useState(0);
  const [auto, setAuto] = useState(true),
    [lastUpdate, setLastUpdate] = useState<Date | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [banner, setBanner] = useState(true);
  const [loading, setLoading] = useState(false);
  const [modelInfo, setModelInfo] = useState<{
    mode: string;
    subtitle_translation_configured: boolean;
    speech_dubbing_available: boolean;
    khmer_dubbing_enabled?: boolean;
  } | null>(null);
  const [playback, setPlayback] = useState<{
      video_url: string;
      captions_url: string | null;
    } | null>(null),
    [previewError, setPreviewError] = useState("");
  const [sourceMode, setSourceMode] = useState<"upload" | "url">("upload"),
    [streamUrl, setStreamUrl] = useState(""),
    [captureSeconds, setCaptureSeconds] = useState(30);
  const input = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null),
    resumeTime = useRef(0),
    resumePlaying = useRef(false);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected?.id || null;
  const currentKey = useRef(key);
  currentKey.current = key;
  const qref = useRef(0);
  qref.current = offset;
  const req = async <T,>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> => {
    const r = await fetch(path, {
      ...options,
      headers: { "X-API-Key": currentKey.current, ...options.headers },
    });
    if (!r.ok) {
      let message = await r.text();
      try {
        message = JSON.parse(message).detail || message;
      } catch {}
      throw new Error(r.status + ": " + String(message).slice(0, 220));
    }
    return (await r.json()) as T;
  };
  const authReady = !!key || !!account?.authenticated;
  const loadAccount = async () => {
    try {
      const [a, p] = await Promise.all([
        fetch("/api/auth/me").then((r) => r.json()),
        fetch("/api/auth/providers").then((r) => r.json()),
      ]);
      setAccount(a);
      setProviders(p.providers || []);
    } catch {
      setAccount(null);
      setProviders([]);
    }
  };
  useEffect(() => {
    void loadAccount();
  }, []);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 760px)");
    const update = () => {
      setIsMobile(media.matches);
      if (!media.matches) setMobileNav(false);
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (page !== "users" || !key || account?.authenticated) return;
    void req<{ items: DirectoryUser[]; total: number }>(
      "/api/users?limit=50&offset=0",
    )
      .then((r) => {
        setDirectory(r.items);
        setDirectoryTotal(r.total);
      })
      .catch((e) => setError(String(e)));
  }, [page, key, account?.authenticated]);
  const setSidebar = (mode: "expanded" | "collapsed" | "hidden") => {
    localStorage.setItem("khmerlive_sidebar_mode", mode);
    setSidebarMode(mode);
  };
  const toggleSidebar = () => setSidebar(collapsed ? "expanded" : "collapsed");
  const toggleSidebarVisibility = () =>
    setSidebar(hidden ? "expanded" : "hidden");
  const refresh = async (silent = false) => {
    if (!currentKey.current && !account?.authenticated) return;
    if (!silent) setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(qref.current),
        status: filter,
      });
      const [q, m, s, models] = await Promise.all([
        req<QueueData>("/api/jobs?" + params),
        req<Metrics>("/api/dashboard"),
        req<SystemData>("/api/system"),
        req<{
          mode: string;
          subtitle_translation_configured: boolean;
          speech_dubbing_available: boolean;
          khmer_dubbing_enabled?: boolean;
        }>("/api/models"),
      ]);
      setModelInfo(models);
      setQueue(q.items);
      setTotal(q.total);
      setMetrics(m);
      setServices(s.services);
      setLastUpdate(new Date());
      if (selectedRef.current) {
        const j = await req<Job>("/api/jobs/" + selectedRef.current);
        setSelected(j);
      }
      if (!silent) setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      if (!silent) setLoading(false);
    }
  };
  useEffect(() => {
    void refresh();
  }, [key, account?.authenticated, filter, offset]);
  useEffect(() => {
    if (!authReady || !auto) return;
    const timer = window.setInterval(() => void refresh(true), 8000);
    return () => clearInterval(timer);
  }, [key, account?.authenticated, auto, filter, offset]);
  useEffect(() => {
    let closed = false;
    setPlayback(null);
    setPreviewError("");
    resumeTime.current = 0;
    resumePlaying.current = false;
    if (
      !selected?.id ||
      !selected.has_output ||
      (!key && !account?.authenticated)
    )
      return;
    const load = async () => {
      try {
        const p = await req<{ video_url: string; captions_url: string | null }>(
          "/api/jobs/" + selected.id + "/player-token",
        );
        if (!closed) {
          if (videoRef.current) {
            resumeTime.current = videoRef.current.currentTime;
            resumePlaying.current = !videoRef.current.paused;
          }
          setPlayback(p);
          setPreviewError("");
        }
      } catch (e) {
        if (!closed) {
          setPreviewError(String(e));
          setPlayback(null);
        }
      }
    };
    void load();
    // Playback grants are intentionally short-lived; refresh while preview is open.
    const timer = window.setInterval(() => void load(), 120000);
    return () => {
      closed = true;
      window.clearInterval(timer);
    };
  }, [selected?.id, selected?.has_output, key, account?.authenticated]);
  const change = (p: Page) => {
    setPage(p);
    setFilter(p === "results" || p === "library" ? "completed" : "all");
    setOffset(0);
    setMobileNav(false);
  };
  const saveKey = () => {
    const k = keyDraft.trim();
    sessionStorage.setItem("khmerlive_api_key", k);
    setKey(k);
    setKeyModal(false);
    setError("");
    setNotice("API key updated for this browser session");
  };
  const choose = (f: File | undefined) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".mp4")) {
      setError(
        "Only MP4 files are supported. Export your video as MP4 (H.264).",
      );
      return;
    }
    setFile(f);
    setError("");
  };
  const submit = async () => {
    if (
      modelsMissing ||
      !authReady ||
      (sourceMode === "upload" && !file) ||
      (sourceMode === "url" && !streamUrl.trim())
    )
      return;
    setBusy(true);
    setUploadPct(sourceMode === "upload" ? 0 : null);
    setError("");
    setNotice("");
    try {
      if (sourceMode === "url") {
        const j = await req<{ job_id: string }>("/api/jobs/from-url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: streamUrl.trim(),
            capture_seconds: captureSeconds,
            source_lang: language,
            target_lang: language === "km" ? "en" : "km",
          }),
        });
        setSelected(await req<Job>("/api/jobs/" + j.job_id));
        setStreamUrl("");
        change("queue");
        setNotice(
          isReal
            ? "URL processing queued; review the completed output for actual audio behavior."
            : "Stream capture queued (demo). Output retains original audio.",
        );
        void refresh();
        return;
      }
      if (!file) return;
      const media = await new Promise<{ media_id: string }>(
        (resolve, reject) => {
          const x = new XMLHttpRequest();
          x.open("POST", "/api/media");
          if (key) x.setRequestHeader("X-API-Key", key);
          x.upload.onprogress = (e) => {
            if (e.lengthComputable)
              setUploadPct(Math.round((e.loaded * 100) / e.total));
          };
          x.onerror = () =>
            reject(new Error("Network error while uploading video"));
          x.onload = () => {
            if (x.status < 200 || x.status >= 300) {
              reject(
                new Error(
                  "Upload failed " +
                    x.status +
                    ": " +
                    x.responseText.slice(0, 180),
                ),
              );
              return;
            }
            try {
              resolve(JSON.parse(x.responseText));
            } catch {
              reject(new Error("Unexpected upload response"));
            }
          };
          const d = new FormData();
          d.append("file", file);
          x.send(d);
        },
      );
      const j = await req<{ job_id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          media_id: media.media_id,
          source_lang: language,
          target_lang: language === "km" ? "en" : "km",
        }),
      });
      setSelected(await req<Job>("/api/jobs/" + j.job_id));
      setFile(null);
      if (input.current) input.current.value = "";
      change("queue");
      setNotice(
        isReal
          ? language === "en" &&
            modelInfo?.khmer_dubbing_enabled &&
            modelInfo?.speech_dubbing_available
            ? "Khmer voice dubbing and subtitles queued"
            : "Translation and subtitles queued"
          : "Demo job added to the live queue",
      );
      void refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setUploadPct(null);
    }
  };
  const action = async (j: Job, which: "cancel" | "retry") => {
    if (
      which === "cancel" &&
      !window.confirm(
        "Request cancellation for " +
          j.filename +
          "? The current processing step may need to finish.",
      )
    )
      return;
    setError("");
    try {
      await req("/api/jobs/" + j.id + "/" + which, { method: "POST" });
      setNotice(
        which === "retry"
          ? "Retry requested. Job was re-queued."
          : "Cancellation requested. Check status for confirmation.",
      );
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };
  const downloadSubtitles = async (j: Job) => {
    try {
      const r = await fetch("/api/jobs/" + j.id + "/subtitles", {
        headers: { "X-API-Key": key },
      });
      if (!r.ok) throw new Error("Subtitles unavailable: " + r.status);
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = j.filename.replace(/\.mp4$/i, "") + "-translated.srt";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) {
      setError(String(e));
    }
  };
  const download = async (j: Job) => {
    try {
      // The browser downloads directly from the S3 streaming proxy; avoid loading
      // large MP4 files into a memory-hungry JavaScript Blob.
      const p = await req<{ video_url: string }>(
        "/api/jobs/" + j.id + "/player-token",
      );
      const anchor = document.createElement("a");
      anchor.href = p.video_url + "&download=1";
      anchor.download = downloadName(j.filename);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (e) {
      setError(String(e));
    }
  };
  const isReal = modelInfo?.mode === "real_subtitles";
  const modelsMissing =
    isReal &&
    (modelInfo?.subtitle_translation_configured === false ||
      (language === "en" &&
        modelInfo?.khmer_dubbing_enabled === true &&
        !modelInfo?.speech_dubbing_available));
  const operating = Object.values(services).filter(
    (v) => v === "online",
  ).length;
  const active = metrics.queued + metrics.processing;
  const totals = [
    ["Total jobs", metrics.total, "All time", "blue"],
    [
      "In progress",
      active,
      metrics.processing + " processing · " + metrics.queued + " queued",
      "sky",
    ],
    ["Completed", metrics.completed, "Ready to download", "green"],
    ["Failed", metrics.failed, "Needs attention", "orange"],
  ] as const;
  const filterTabs: [string, string, number][] = [
    ["all", "All", metrics.total],
    ["active", "Active", active],
    ["completed", "Completed", metrics.completed],
    ["failed", "Failed", metrics.failed],
  ];
  const listPanel = (
    <section className="card jobs-card" aria-label="Recent jobs">
      <div className="jobs-head">
        <div className="section-title">
          <h2>{page === "results" ? "Completed results" : "Recent jobs"}</h2>
          <span className="live-dot">● Live</span>
        </div>
        <div className="tabs" role="tablist" aria-label="Job status filter">
          {filterTabs.map(([id, name, n]) => (
            <button
              key={id}
              role="tab"
              aria-selected={filter === id}
              className={filter === id ? "active" : ""}
              onClick={() => {
                setFilter(id);
                setOffset(0);
              }}
            >
              {name} <span>{n}</span>
            </button>
          ))}
        </div>
        <label className="switch-label">
          Auto-refresh{" "}
          <input
            type="checkbox"
            role="switch"
            checked={auto}
            onChange={(e) => setAuto(e.target.checked)}
          />
        </label>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Video</th>
              <th>Language</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Created</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {queue.map((j) => (
              <tr
                key={j.id}
                className={selected?.id === j.id ? "selected" : ""}
                onClick={() => setSelected(j)}
              >
                <td>
                  <div className="video-cell">
                    <div className="thumb" aria-hidden="true">
                      ▶
                    </div>
                    <div className="file-info">
                      <strong title={j.filename}>{j.filename}</strong>
                      <small>
                        {j.source_kind === "url" ? "◉ URL stream" : "⇧ Upload"}{" "}
                        · #{j.id.slice(0, 8)} · {size(j.size_bytes)}
                      </small>
                    </div>
                  </div>
                </td>
                <td>
                  <span className="language-cell">
                    {j.source_lang === "km" ? "Khmer" : "English"}
                    <small>({j.source_lang})</small>
                  </span>
                </td>
                <td>
                  <Badge status={j.status} />
                </td>
                <td>
                  <div className="job-progress">
                    <span>
                      {j.status === "queued"
                        ? "Waiting"
                        : j.status === "cancelled"
                          ? "Stopped"
                          : j.progress + "%"}
                    </span>
                    <div className="progress-track">
                      <i
                        className={finalStatus(j.status)}
                        style={{ width: j.progress + "%" }}
                      />
                    </div>
                  </div>
                </td>
                <td className="age">{elapsed(j.created_at)}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  {j.has_output ? (
                    <button
                      className="outline success"
                      onClick={() => void download(j)}
                    >
                      MP4
                    </button>
                  ) : ["queued", "processing", "cancelling"].includes(
                      j.status,
                    ) ? (
                    <button
                      className="outline"
                      disabled={j.status === "cancelling"}
                      onClick={() => void action(j, "cancel")}
                    >
                      {j.status === "cancelling" ? "Pending" : "Cancel"}
                    </button>
                  ) : (
                    <button
                      className="outline warning"
                      onClick={() => void action(j, "retry")}
                    >
                      Retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {loading &&
              !queue.length &&
              Array.from({ length: 3 }, (_, i) => (
                <tr key={i}>
                  <td colSpan={6}>
                    <div className="skeleton" />
                  </td>
                </tr>
              ))}
            {!loading && queue.length === 0 && (
              <tr>
                <td colSpan={6}>
                  <div className="empty-state">
                    <strong>No matching jobs yet</strong>
                    <p>
                      Upload a video or enter a stream URL to see it move
                      through the pipeline.
                    </p>
                    <button className="primary" onClick={() => change("new")}>
                      Start a new job
                    </button>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="pagination">
        <span>
          Showing {total ? offset + 1 : 0}–{Math.min(offset + limit, total)} of{" "}
          {total} jobs
        </span>
        <div>
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(offset - limit, 0))}
          >
            ‹
          </button>
          <span>{Math.floor(offset / limit) + 1}</span>
          <button
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
          >
            ›
          </button>
        </div>
      </div>
    </section>
  );
  const isUrlSource = selected?.source_kind === "url";
  const phases = isUrlSource
    ? [
        "URL submitted",
        "Stream captured",
        "Queued for processing",
        "Worker processing",
        "Saved to storage",
      ]
    : [
        "Upload received",
        "File validated",
        "Queued",
        "Worker processing",
        "Saved to storage",
      ];
  const current = selected?.status || "queued";
  const isComplete = current === "completed";
  const capturing = !!selected?.stage?.toLowerCase().includes("captur");
  const step = isComplete
    ? 5
    : isUrlSource && current === "queued"
      ? 1
      : isUrlSource && capturing
        ? 2
        : current === "queued"
          ? 3
          : current === "processing" || current === "cancelling"
            ? 4
            : current === "failed" || current === "dispatch_failed"
              ? 3
              : current === "cancelled"
                ? 3
                : 0;
  const details = (
    <section className="card detail-card">
      <div className="detail-top">
        <h2>{selected ? "Job #" + selected.id.slice(0, 8) : "Job details"}</h2>
        {selected && <Badge status={selected.status} />}
      </div>
      {selected?.has_output ? (
        <div className="preview-ready">
          <div className="preview-banner">
            {selected.has_khmer_voice
              ? "Khmer voice dubbing + translated subtitles"
              : selected.has_subtitles
                ? "Translated subtitles available · Original speech retained"
                : "Demo video · Original speech retained"}
          </div>
          {playback ? (
            <video
              ref={videoRef}
              key={selected.id + playback.video_url}
              className="preview-video"
              controls
              playsInline
              preload="metadata"
              src={playback.video_url}
              aria-label="Review processed video"
              onLoadedMetadata={(e) => {
                if (resumeTime.current > 0)
                  e.currentTarget.currentTime = resumeTime.current;
                if (resumePlaying.current)
                  void e.currentTarget.play().catch(() => {});
              }}
              onTimeUpdate={(e) => {
                resumeTime.current = e.currentTarget.currentTime;
              }}
              onPlay={() => {
                resumePlaying.current = true;
              }}
              onPause={() => {
                resumePlaying.current = false;
              }}
            >
              {playback.captions_url && (
                <track
                  kind="subtitles"
                  label={
                    selected.target_lang === "km"
                      ? "Khmer subtitles"
                      : "English subtitles"
                  }
                  srcLang={selected.target_lang}
                  src={playback.captions_url}
                  default
                />
              )}
              Your browser cannot play this video.
            </video>
          ) : (
            <div className="preview">
              <span>▶</span>
              <small>{previewError || "Loading secure video preview…"}</small>
            </div>
          )}
        </div>
      ) : (
        <div
          className="preview"
          role="img"
          aria-label="Preview will be available after processing"
        >
          <span>▶</span>
          <small>Review video after the job is completed.</small>
        </div>
      )}
      {selected ? (
        <>
          <div className="details-grid">
            <div>
              <small>File</small>
              <strong title={selected.filename}>{selected.filename}</strong>
            </div>
            <div>
              <small>Language</small>
              <strong>
                {selected.source_lang === "km" ? "Khmer" : "English"} (
                {selected.source_lang})
              </strong>
            </div>
            <div>
              <small>Source</small>
              <strong>
                {selected.source_kind === "url"
                  ? "URL Stream (" + (selected.capture_seconds || 30) + "s)"
                  : "MP4 Upload"}
              </strong>
            </div>
            <div>
              <small>Job ID</small>
              <strong title={selected.id}>#{selected.id.slice(0, 8)}</strong>
              <button
                className="copy"
                onClick={() => void navigator.clipboard.writeText(selected.id)}
              >
                Copy
              </button>
            </div>
          </div>
          {(selected.transcript || selected.translation) && (
            <details className="translation-review">
              <summary>
                Review recognition & translated text (live updates for URL)
              </summary>
              <div>
                <strong>
                  Recognized speech · {selected.source_lang.toUpperCase()}
                </strong>
                <p>{selected.transcript || "No transcript"}</p>
                <strong>
                  Translated · {selected.target_lang.toUpperCase()}
                </strong>
                <p>{selected.translation || "No translation"}</p>
              </div>
            </details>
          )}
          <div className="pipeline">
            <h3>Pipeline</h3>
            {phases.map((title, i) => {
              const done = i < step && (isComplete || i < step - 1);
              const currentStep =
                i === step - 1 &&
                !isComplete &&
                ["queued", "processing", "cancelling"].includes(current);
              return (
                <div className="pipeline-row" key={title}>
                  <div
                    className={
                      "node " +
                      (done
                        ? "done"
                        : currentStep
                          ? "running"
                          : current === "failed" && i === step - 1
                            ? "problem"
                            : "")
                    }
                  >
                    {done ? "✓" : currentStep ? "◉" : ""}
                  </div>
                  <div>
                    <strong>{title}</strong>
                    <small>
                      {done
                        ? "Complete"
                        : currentStep
                          ? selected.stage || label(current)
                          : current === "failed" && i === step - 1
                            ? "Stopped"
                            : "Waiting"}
                    </small>
                  </div>
                </div>
              );
            })}
          </div>
          {selected.error && (
            <div className="inline-error">
              <b>Job failed</b>
              <p>{selected.error}</p>
            </div>
          )}
          <div className="detail-buttons">
            {selected.has_output ? (
              <>
                <button
                  className="primary"
                  onClick={() => void download(selected)}
                >
                  Download{" "}
                  {selected.has_khmer_voice
                    ? "Khmer dubbed"
                    : selected.has_subtitles
                      ? "subtitled"
                      : "demo"}{" "}
                  MP4
                </button>
                {selected.has_subtitles && (
                  <button
                    className="outline"
                    onClick={() => void downloadSubtitles(selected)}
                  >
                    Download SRT
                  </button>
                )}
              </>
            ) : ["failed", "dispatch_failed", "cancelled"].includes(
                selected.status,
              ) ? (
              <button
                className="primary"
                onClick={() => void action(selected, "retry")}
              >
                Retry job
              </button>
            ) : (
              <button
                className="primary"
                disabled={selected.status === "cancelling"}
                onClick={() => void action(selected, "cancel")}
              >
                {selected.status === "cancelling"
                  ? "Cancelling…"
                  : "Cancel job"}
              </button>
            )}
            <button className="outline" onClick={() => void refresh()}>
              Refresh status
            </button>
          </div>
        </>
      ) : (
        <div className="details-empty">
          Select a row from Recent jobs to inspect its processing stages and
          available actions.
        </div>
      )}
    </section>
  );
  const userPanel = (
    <section className="card accounts-card">
      <div className="account-heading">
        <div>
          <h2>Users & connected accounts</h2>
          <p>
            Sign in securely or link social identities to one KhmerLive account.
          </p>
        </div>
        <span className="research-pill">OAuth 2.0 / OIDC</span>
      </div>
      {account?.authenticated ? (
        <>
          <div className="account-profile">
            <span className="profile-avatar">
              {account.user?.name?.slice(0, 1).toUpperCase() || "U"}
            </span>
            <div>
              <strong>{account.user?.name}</strong>
              <small>
                {account.user?.email || "Email not provided by provider"}
              </small>
              <small>Private user ID: {account.user?.id.slice(0, 8)}…</small>
            </div>
            <button
              className="outline"
              onClick={async () => {
                await fetch("/api/auth/logout", { method: "POST" });
                setAccount(null);
                setSelected(null);
                setQueue([]);
                setMetrics(empty);
                setNotice("Signed out");
                void loadAccount();
              }}
            >
              Sign out
            </button>
          </div>
          <h3>Linked social accounts</h3>
          <div className="social-list">
            {account.identities.map((i) => (
              <div className="social-row" key={i.provider}>
                <strong>
                  {i.provider === "google"
                    ? "🌐 Google"
                    : i.provider === "github"
                      ? "◈ GitHub"
                      : "ⓕ Facebook"}
                </strong>
                <span>Connected · {i.display_name || i.provider}</span>
                <span className="status-chip status-completed">✓ Linked</span>
              </div>
            ))}
          </div>
          <h3>Connect another account</h3>
        </>
      ) : (
        <div className="account-hint">
          You can sign in with a supported social account after an administrator
          configures its OAuth credentials. API key access remains available for
          trusted local admin testing.
        </div>
      )}
      <div className="provider-actions">
        {providers.map((p) => (
          <div className="provider-card" key={p.id}>
            <strong>
              {p.id === "google" ? "🌐" : p.id === "github" ? "◈" : "ⓕ"}{" "}
              {p.name}
            </strong>
            <small>
              {p.enabled ? "OAuth configured" : "Not configured on server"}
            </small>
            <button
              className={p.enabled ? "primary" : "outline"}
              disabled={
                !p.enabled ||
                !!account?.identities.some((i) => i.provider === p.id)
              }
              onClick={() => {
                window.location.href =
                  "/api/auth/" +
                  (account?.authenticated ? "link" : "login") +
                  "/" +
                  p.id;
              }}
            >
              {account?.identities.some((i) => i.provider === p.id)
                ? "Already linked"
                : account?.authenticated
                  ? "Link account"
                  : "Sign in"}
            </button>
          </div>
        ))}
        {!providers.length && <p>OAuth providers could not be loaded.</p>}
      </div>
      {key && !account?.authenticated && (
        <div className="user-directory">
          <h3>
            Registered users <small>({directoryTotal})</small>
          </h3>
          <p className="account-footnote">
            Admin-only directory via your API key. Social users see only their
            own account.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Connected providers</th>
                  <th>Registered</th>
                </tr>
              </thead>
              <tbody>
                {directory.map((u) => (
                  <tr key={u.id}>
                    <td>{u.display_name}</td>
                    <td>{u.email || "—"}</td>
                    <td>{u.providers.join(", ") || "—"}</td>
                    <td>{asDate(u.created_at)}</td>
                  </tr>
                ))}
                {!directory.length && (
                  <tr>
                    <td colSpan={4}>No users registered yet</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="account-footnote">
        Social tokens are not stored. A Google or Facebook developer app,
        callback URL and server-side credentials are required. Accounts are
        isolated by owner in PostgreSQL.
      </p>
    </section>
  );
  const uploadPanel = (
    <section className="card upload-card">
      <div className="card-head">
        <h2>Start a new job</h2>
        <span>
          {account?.authenticated ? (
            "Signed in: " + account.user?.name
          ) : (
            <>
              API Key{" "}
              <code>
                {key ? key.slice(0, 3) + "_••••" + key.slice(-4) : "not set"}
              </code>{" "}
              ·{" "}
              <button
                className="text-link"
                onClick={() => {
                  setKeyDraft(key);
                  setKeyModal(true);
                }}
              >
                Change
              </button>
            </>
          )}
        </span>
      </div>
      <div
        className="source-picker"
        role="tablist"
        aria-label="Video input source"
      >
        <button
          className={sourceMode === "upload" ? "chosen" : ""}
          role="tab"
          aria-selected={sourceMode === "upload"}
          onClick={() => setSourceMode("upload")}
        >
          <Icon name="upload" /> Upload MP4
        </button>
        <button
          className={sourceMode === "url" ? "chosen" : ""}
          role="tab"
          aria-selected={sourceMode === "url"}
          onClick={() => setSourceMode("url")}
        >
          <Icon name="link" /> Stream by URL
        </button>
      </div>
      <div className="upload-layout">
        <div>
          <label className="field-label">
            {sourceMode === "upload" ? "1 · Video file" : "1 · Stream URL"}
          </label>
          {sourceMode === "upload" ? (
            <div
              className="drop-zone"
              tabIndex={0}
              role="button"
              onClick={() => input.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter") input.current?.click();
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                choose(e.dataTransfer.files[0]);
              }}
            >
              <span className="cloud">☁</span>
              <strong>
                {file ? file.name : "Drop an MP4 here, or "}{" "}
                {!file && <u>browse files</u>}
              </strong>
              <small>
                {file
                  ? size(file.size)
                  : "MP4 (H.264) · max 1 GiB configured by default"}
              </small>
              <input
                ref={input}
                type="file"
                accept=".mp4,video/mp4"
                hidden
                onChange={(e) => choose(e.target.files?.[0])}
              />
            </div>
          ) : (
            <div className="url-source">
              <input
                aria-label="Stream URL"
                type="url"
                placeholder="https://video.example.org/live/index.m3u8"
                value={streamUrl}
                onChange={(e) => setStreamUrl(e.target.value)}
              />
              <small>
                Direct HTTP(S) MP4 or HLS (.m3u8) only. YouTube watch URLs are
                not yet supported. The host must be allowlisted.
              </small>
              <label className="field-label" htmlFor="capture-duration">
                Capture duration
              </label>
              <select
                id="capture-duration"
                value={captureSeconds}
                onChange={(e) => setCaptureSeconds(Number(e.target.value))}
              >
                <option value={15}>15 seconds</option>
                <option value={30}>30 seconds</option>
                <option value={60}>60 seconds</option>
                <option value={120}>120 seconds</option>
              </select>
              <small>
                Near-live caption updates per recorded chunk (model speed
                dependent). Bounded 15–120 second recording; not continuous
                voice dubbing.
              </small>
            </div>
          )}
        </div>
        <div>
          <label className="field-label" htmlFor="spoken">
            2 · Spoken language
          </label>
          <select
            id="spoken"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          >
            <option value="km">Khmer · ខ្មែរ (km)</option>
            <option value="en">English (en)</option>
          </select>
          <p className="help">
            English → Khmer and Khmer → English. Choose the language spoken in
            your video.
          </p>
          <div className="language-target">
            <b>Translation output</b>
            <span>
              {language === "en" ? "🇰🇭 Khmer (km)" : "🇬🇧 English (en)"}
            </span>
          </div>
          {uploadPct !== null && (
            <div className="upload-progress">
              Uploading {uploadPct}%
              <div className="progress-track">
                <i style={{ width: uploadPct + "%" }} />
              </div>
            </div>
          )}
          <button
            className="primary submit"
            disabled={
              modelsMissing ||
              !authReady ||
              busy ||
              (sourceMode === "upload" ? !file : !streamUrl.trim())
            }
            onClick={() => void submit()}
          >
            → &nbsp;
            {busy
              ? "Submitting…"
              : sourceMode === "upload"
                ? isReal
                  ? language === "en" &&
                    modelInfo?.khmer_dubbing_enabled &&
                    modelInfo?.speech_dubbing_available
                    ? "Dub into Khmer"
                    : "Translate and subtitle"
                  : "Submit demo job"
                : isReal
                  ? "Process URL stream"
                  : "Capture stream demo"}
          </button>
          <small className="submit-hint">
            {sourceMode === "url"
              ? "Approved direct MP4/HLS URLs only; YouTube watch-page URLs are not supported yet."
              : !file
                ? "Add an MP4 to enable submit."
                : isReal &&
                    language === "en" &&
                    modelInfo?.khmer_dubbing_enabled &&
                    modelInfo?.speech_dubbing_available
                  ? "Khmer voice and subtitles will be generated; review output before sharing."
                  : "Original speech is preserved unless Khmer dubbing is configured."}
          </small>
        </div>
      </div>
    </section>
  );
  const libraryPanel = (
    <section className="library-layout" aria-label="Completed video library">
      <div className="library-toolbar card">
        <div>
          <strong>{total} completed {total === 1 ? "video" : "videos"}</strong>
          <span>Only real completed outputs returned by the API appear here.</span>
        </div>
        <button className="outline" onClick={() => void refresh()}>Refresh library</button>
      </div>
      <div className="video-grid">
        {queue.map((job) => (
          <article className="card video-card" key={job.id}>
            <button
              className="video-card-preview"
              onClick={() => { setSelected(job); change("results"); }}
              aria-label={`Open ${job.filename}`}
            >
              <Icon name="result" />
              <span>{job.has_khmer_voice ? "Khmer dubbed" : job.has_subtitles ? "Subtitled" : "Demo output"}</span>
            </button>
            <div className="video-card-body">
              <div>
                <strong title={job.filename}>{job.filename}</strong>
                <small>{asDate(job.created_at)}</small>
              </div>
              <Badge status={job.status} />
            </div>
            <div className="video-card-meta">
              <span>{job.source_kind === "url" ? "URL capture" : "MP4 upload"}</span>
              <span>{job.source_lang.toUpperCase()} → {job.target_lang.toUpperCase()}</span>
            </div>
            <div className="video-card-actions">
              <button className="outline" onClick={() => { setSelected(job); change("results"); }}>Review</button>
              <button className="primary" onClick={() => void download(job)}>Download</button>
            </div>
          </article>
        ))}
        {!loading && queue.length === 0 && (
          <div className="card library-empty">
            <Icon name="library" />
            <h2>No completed videos yet</h2>
            <p>Completed jobs will appear here automatically. Start with a short permission-cleared MP4.</p>
            <button className="primary" onClick={() => change("new")}>New translation</button>
          </div>
        )}
      </div>
    </section>
  );
  const modelRows = [
    { name: "Whisper", role: "Speech recognition (ASR)", ready: !!modelInfo?.subtitle_translation_configured, detail: "Local faster-whisper model" },
    { name: "M2M100", role: "English ↔ Khmer translation", ready: !!modelInfo?.subtitle_translation_configured, detail: "Local multilingual translation model" },
    { name: "Khmer MMS VITS", role: "Khmer text-to-speech", ready: !!modelInfo?.speech_dubbing_available, detail: modelInfo?.khmer_dubbing_enabled ? "Dubbing enabled by server configuration" : "Dubbing disabled by server configuration" },
  ];
  const modelsPanel = (
    <section className="models-layout">
      <div className="card model-summary">
        <div>
          <span className="eyebrow">INFERENCE MODE</span>
          <h2>{isReal ? "Local AI processing" : "Research demo"}</h2>
          <p>{isReal ? "Jobs use offline model files available to the worker." : "Demo jobs do not perform speech recognition, translation, or dubbing."}</p>
        </div>
        <span className={`readiness-badge ${isReal && modelRows.every((m) => m.ready) ? "ready" : "attention"}`}>
          {isReal && modelRows.every((m) => m.ready) ? "All configured" : "Setup required"}
        </span>
      </div>
      <div className="model-grid">
        {modelRows.map((model, index) => (
          <article className="card model-card" key={model.name}>
            <div className={`model-icon model-${index}`}><Icon name="models" /></div>
            <div className="model-copy">
              <span className="eyebrow">{model.role}</span>
              <h2>{model.name}</h2>
              <p>{model.detail}</p>
            </div>
            <span className={`readiness-badge ${model.ready ? "ready" : "attention"}`}>
              {model.ready ? "Ready" : isReal ? "Missing" : "Inactive"}
            </span>
          </article>
        ))}
      </div>
      <div className="card model-notice">
        <strong>License and quality notice</strong>
        <p>Model readiness only confirms that required files are present. It does not prove translation accuracy, Khmer pronunciation quality, synchronization quality, or commercial license suitability.</p>
      </div>
    </section>
  );
  const systemPanel = (
    <section className="health-layout">
      <div className="card system-card">
        <div className="section-title">
          <div><span className="eyebrow">LIVE INFRASTRUCTURE</span><h2>Service health</h2></div>
          <button className="outline" onClick={() => void refresh()}>Refresh</button>
        </div>
        {["api", "worker", "database", "redis", "storage"].map((s) => (
          <div className="service-row" key={s}>
            <span className="service-name"><i className={services[s] === "online" ? "service-dot online" : "service-dot"}/><strong>{s === "database" ? "PostgreSQL" : s === "worker" ? "Celery worker" : s === "storage" ? "Object storage" : s.toUpperCase()}</strong></span>
            <span className={services[s] || "unknown"}>{services[s] || "unknown"}</span>
          </div>
        ))}
        <p>Unreachable checks are not displayed as operational. Worker ping may be unknown.</p>
      </div>
      <aside className="card environment-card">
        <span className="eyebrow">ENVIRONMENT</span>
        <h2>{isReal ? "Real model mode" : "Demo mode"}</h2>
        <dl>
          <div><dt>Healthy services</dt><dd>{operating}/5</dd></div>
          <div><dt>Subtitle pipeline</dt><dd>{modelInfo?.subtitle_translation_configured ? "Ready" : "Not ready"}</dd></div>
          <div><dt>Khmer voice</dt><dd>{modelInfo?.speech_dubbing_available ? "Ready" : "Not ready"}</dd></div>
          <div><dt>Last checked</dt><dd>{lastUpdate ? elapsed(lastUpdate.toISOString()) : "Not checked"}</dd></div>
        </dl>
      </aside>
    </section>
  );
  return (
    <div
      className={
        "app-shell" +
        (collapsed ? " sidebar-collapsed" : "") +
        (hidden ? " sidebar-hidden" : "") +
        (mobileNav ? " nav-open" : "")
      }
    >
      <header className="topbar">
        <div className="brand">
          <button
            className="nav-toggle"
            aria-label={
              isMobile
                ? mobileNav
                  ? "Close navigation"
                  : "Open navigation"
                : hidden
                  ? "Show sidebar"
                  : "Hide sidebar"
            }
            aria-expanded={mobileNav}
            aria-controls="primary-sidebar"
            onClick={() => {
              if (isMobile) setMobileNav((v) => !v);
              else toggleSidebarVisibility();
            }}
          >
            <Icon name="menu" />
          </button>
          <span className="logo">
            <img src="/khmerlive-logo.svg" alt="" width="34" height="34" />
          </span>
          <strong>KhmerLive AI</strong>
          <span className="research-pill">
            {isReal ? "LOCAL AI MODE" : "RESEARCH DEMO"}
          </span>
        </div>
        <div className="top-actions">
          <div
            className={
              "global-health " + (operating === 5 ? "healthy" : "partial")
            }
          >
            <span>●</span>{" "}
            {operating === 5 ? "All systems operational" : "System status"}{" "}
            <b>{operating}/5</b>
          </div>
          <button
            className="help-button"
            title="API documentation"
            onClick={() => window.open("/api/docs", "_blank", "noopener")}
          >
            ?
          </button>
          <button className="user-button" onClick={() => change("users")}>
            {account?.authenticated
              ? account.user?.name?.slice(0, 1).toUpperCase() || "U"
              : "KL"}
            　⌄
          </button>
        </div>
      </header>
      {banner && (
        <div className="demo-banner">
          <span>♧</span>
          <p>
            <b>{isReal ? "Local model processing." : "Demo mode."}</b>{" "}
            {isReal
              ? modelInfo?.khmer_dubbing_enabled &&
                modelInfo?.speech_dubbing_available
                ? "Khmer voice dubbing is configured for English-to-Khmer jobs. Validate actual audio quality before release."
                : "Offline translation and subtitles are configured; Khmer voice dubbing may not be available."
              : "No real speech recognition, translation or dubbing runs in demo mode."}
          </p>
          <button
            aria-label="Dismiss demo notice"
            onClick={() => setBanner(false)}
          >
            ×
          </button>
        </div>
      )}
      <div className="body-layout">
        {mobileNav && (
          <button
            className="mobile-scrim"
            aria-label="Close navigation"
            onClick={() => setMobileNav(false)}
          />
        )}
        <aside
          id="primary-sidebar"
          className="sidebar"
          aria-label="Primary navigation"
        >
          <div className="sidebar-controls">
            <button
              className="sidebar-collapse"
              onClick={toggleSidebar}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? "»" : "«"}{" "}
              <span>{collapsed ? "Expand" : "Collapse"}</span>
            </button>
            <button
              className="sidebar-hide"
              onClick={toggleSidebarVisibility}
              title="Hide sidebar"
              aria-label="Hide sidebar"
            >
              × <span>Hide</span>
            </button>
          </div>
          <div className="nav-label">WORKSPACE</div>
          <nav>
            {workspacePages.map(([id, icon, title]) => (
              <button
                className={page === id ? "current" : ""}
                key={id}
                onClick={() => change(id)}
                title={collapsed ? title : undefined}
              >
                <span><Icon name={icon} /></span>
                {title}
                {id === "queue" && active > 0 && <b>{active}</b>}
              </button>
            ))}
          </nav>
          <div className="sidebar-divider" />
          <div className="nav-label">MANAGE</div>
          <nav>
            {managePages.map(([id, icon, title]) => (
              <button
                className={page === id ? "current" : ""}
                key={id}
                onClick={() => change(id)}
                title={collapsed ? title : undefined}
              >
                <span><Icon name={icon} /></span>
                {title}
                {id === "system" && <i className={operating === 5 ? "online" : ""} />}
              </button>
            ))}
          </nav>
          <div className="sidebar-divider" />
          <div className="nav-label">DEVELOPER</div>
          <nav>
            <button
              onClick={() => {
                setKeyDraft(key);
                setKeyModal(true);
              }}
            >
              <span><Icon name="key" /></span>API keys
            </button>
            <button
              onClick={() => window.open("/api/docs", "_blank", "noopener")}
            >
              <span><Icon name="docs" /></span>API docs
            </button>
          </nav>
        </aside>
        <main className="main-area">
          <div className="page-title">
            <div>
              <span className="page-kicker">KHMERLIVE WORKSPACE</span>
              <h1>{pageCopy[page][0]}</h1>
              <p>{pageCopy[page][1]}</p>
            </div>
            <span className="last-update">
              <Icon name="clock" />{" "}
              {lastUpdate
                ? "Updated " + elapsed(lastUpdate.toISOString())
                : "Waiting for connection"}
            </span>
          </div>
          {modelsMissing && (
            <div className="alert error-alert">
              <b>Offline translation or Khmer voice model is missing.</b>{" "}
              Install Whisper, M2M100 and Khmer MMS TTS under models/asr,
              models/mt and models/tts; then restart the real worker. No
              English-to-Khmer dubbing job can start yet.
            </div>
          )}
          {error && (
            <div className="alert error-alert">
              <b>Could not complete the request.</b> {error}
              <button
                onClick={() => {
                  setError("");
                  void refresh();
                }}
              >
                Try again
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success-alert">
              {notice}
              <button onClick={() => setNotice("")}>×</button>
            </div>
          )}
          {!authReady && page !== "users" && (
            <div className="alert error-alert">
              Sign in or set an API key to load live jobs.{" "}
              <button onClick={() => setKeyModal(true)}>Add API key</button>
            </div>
          )}
          {page === "dashboard" ? (
            <>
              <div className="dashboard-hero card">
                <div>
                  <span className="eyebrow">VIDEO TRANSLATION OPERATIONS</span>
                  <h2>{active ? `${active} ${active === 1 ? "job is" : "jobs are"} active` : "Your workspace is ready"}</h2>
                  <p>{isReal ? "Offline inference is enabled. Review model readiness and every generated artifact before release." : "The application is in demo mode; completed demo videos retain their original speech."}</p>
                </div>
                <div className="hero-actions">
                  <button className="outline" onClick={() => change("models")}>Check models</button>
                  <button className="primary" onClick={() => change("new")}><Icon name="plus" /> New translation</button>
                </div>
              </div>
              <div className="metrics-grid dashboard-metrics">
                {totals.map(([title, n, desc, kind]) => (
                  <div className={"metric-card " + kind} key={title}>
                    <span>{title}</span>
                    <b>{n}</b>
                    <small>{desc}</small>
                  </div>
                ))}
              </div>
              <div className="dashboard-bottom">
                {listPanel}
                {details}
              </div>
            </>
          ) : page === "new" ? (
            <div className="new-layout">
              <div>
                <div className="stepper" aria-label="Translation setup steps">
                  <span className="active"><b>1</b> Input</span>
                  <span><b>2</b> Process</span>
                  <span><b>3</b> Review</span>
                </div>
                {uploadPanel}
              </div>
              <aside className="card aside-help">
                <span className="eyebrow">PROCESS OVERVIEW</span>
                <h2>What happens next?</h2>
                <p>
                  The worker validates your source, extracts audio, and records
                  each processing stage in PostgreSQL.
                </p>
                <p>
                  Audio dubbing is available only when real-model mode and Khmer
                  TTS are configured. Demo jobs preserve original audio.
                </p>
                <ol className="process-list">
                  <li><b>Validate source</b><span>Codec, size, duration, and audio stream</span></li>
                  <li><b>Run local pipeline</b><span>ASR, translation, voice, and rendering when configured</span></li>
                  <li><b>Review output</b><span>Preview video and download available artifacts</span></li>
                </ol>
                <button className="outline" onClick={() => change("queue")}>
                  View queue →
                </button>
              </aside>
            </div>
          ) : page === "library" ? (
            libraryPanel
          ) : page === "models" ? (
            modelsPanel
          ) : page === "users" ? (
            userPanel
          ) : page === "system" ? (
            systemPanel
          ) : (
            <div className="dashboard-bottom">
              {listPanel}
              {details}
            </div>
          )}
        </main>
      </div>
      {keyModal && (
        <div className="modal-overlay" onClick={() => setKeyModal(false)}>
          <section className="key-modal" onClick={(e) => e.stopPropagation()}>
            <h2>API key</h2>
            <p>
              Enter the API_KEY from your local .env file. The key stays in this
              browser session and is not committed to GitHub.
            </p>
            <label className="field-label" htmlFor="api-key">
              API key
            </label>
            <input
              id="api-key"
              type="password"
              value={keyDraft}
              onChange={(e) => setKeyDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveKey();
              }}
            />
            <div className="modal-actions">
              <button className="outline" onClick={() => setKeyModal(false)}>
                Cancel
              </button>
              <button className="primary" onClick={saveKey}>
                Save key
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
