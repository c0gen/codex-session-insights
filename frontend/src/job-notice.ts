import type { Job } from "./types";
import { compact } from "./format";
import { count } from "./ui";

type Notice = { message: string; title: string; queue: string; busy: boolean; cancelable: boolean; until: number };
let notice: Notice | undefined;
let observed = false;
let lastCompletion = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let cancelCurrent = () => {};
const readableMilliseconds = 5000;

function paint() {
  if (timer) clearTimeout(timer);
  const banner = document.querySelector<HTMLElement>("#job-banner");
  if (!banner) return;
  if (notice && !notice.busy && performance.now() >= notice.until) notice = undefined;
  banner.hidden = !notice;
  if (!notice) return;
  if (!banner.children.length) {
    banner.innerHTML = '<span class="spinner" aria-hidden="true"></span><span class="job-message"></span><span class="job-queue"></span><button class="text-button" id="cancel-job">Cancel</button><button class="text-button" id="dismiss-job" aria-label="Dismiss status">Dismiss</button>';
  }
  banner.querySelector<HTMLElement>(".spinner")!.hidden = !notice.busy;
  banner.querySelector(".job-message")!.textContent = notice.message;
  banner.querySelector(".job-queue")!.textContent = notice.queue;
  const cancel = banner.querySelector<HTMLButtonElement>("#cancel-job")!;
  cancel.hidden = !notice.cancelable;
  cancel.onclick = cancelCurrent;
  const dismiss = banner.querySelector<HTMLButtonElement>("#dismiss-job")!;
  dismiss.hidden = notice.busy;
  dismiss.onclick = () => { notice = undefined; paint(); };
  if (!notice.busy) timer = setTimeout(paint, Math.max(1, notice.until - performance.now()));
}

/** Preserve a readable completion across dashboard renders and fast jobs. */
export function showJobNotice(job: Job, cancel: () => void) {
  cancelCurrent = cancel;
  const completed = (job.completed || []).filter(item => item.origin === "user" && item.id > lastCompletion).at(-1);
  for (const item of job.completed || []) lastCompletion = Math.max(lastCompletion, item.id);
  const foreground = job.running && job.origin !== "automatic";
  const queued = job.queued || [];
  if (foreground || queued.length) {
    const progress = job.progress || {};
    const detail = progress.sessions
      ? ` · ${count(progress.sessions)} session facts`
      : progress.files ? ` · ${count(progress.files)} files checked · ${compact((progress.bytes_read || 0) / 1024 / 1024)} MB read` : "";
    notice = {
      title: foreground ? job.message : queued[0].message,
      message: foreground ? `${progress.phase || job.message}${detail}` : `Queued · ${queued[0].message}`,
      queue: foreground && queued.length ? ` · ${queued.length} queued` : "",
      busy: true, cancelable: foreground && job.cancelable !== false, until: Infinity,
    };
  } else if ((observed && completed) || notice?.busy) {
    const state = completed?.state || job.state;
    const label = state === "failed" ? "Failed" : state === "cancelled" ? "Cancelled" : "Completed";
    const title = completed?.message || notice?.title || job.message;
    notice = { title, message: `${title} · ${label}`, queue: "", busy: false, cancelable: false,
      until: performance.now() + readableMilliseconds };
  }
  observed = true;
  paint();
}
