import type { ActionResponse, Job, JobCompletion } from "./types";
import { showJobNotice } from "./job-notice";

export function showJob(job: Job, cancel: () => void) {
  const automatic = job.running && job.origin === "automatic";
  const refresh = document.querySelector<HTMLButtonElement>("#refresh");
  if (refresh) {
    refresh.classList.toggle("refreshing", automatic);
    refresh.setAttribute("aria-busy", String(automatic));
    refresh.setAttribute("aria-label", automatic ? "Updating usage" : "Refresh insights");
    refresh.title = automatic ? "Updating usage" : "Refresh insights";
  }
  showJobNotice(job, cancel);
}

type Waiting = {
  resolve: (value: JobCompletion) => void;
  update?: (state: "queued" | "running") => void;
};

/** Completion history makes fast jobs observable even between status polls. */
export class JobFeedback {
  private waiting = new Map<number, Waiting[]>();
  private latest?: Job;
  private lastFailure = 0;

  constructor(private failed: (message: string) => void) {}

  wait(response: ActionResponse, update?: Waiting["update"]) {
    const id = response.job_id!;
    return new Promise<JobCompletion>((resolve) => {
      this.waiting.set(id, [...(this.waiting.get(id) || []), { resolve, update }]);
      if (this.latest) this.observe(this.latest);
    });
  }

  observe(job: Job) {
    this.latest = job;
    for (const completion of job.completed || []) {
      if (completion.id > this.lastFailure && completion.origin === "user" && completion.state === "failed") {
        this.failed(completion.error || "The update failed.");
      }
      this.lastFailure = Math.max(this.lastFailure, completion.id);
      for (const waiting of this.waiting.get(completion.id) || []) waiting.resolve(completion);
      this.waiting.delete(completion.id);
    }
    for (const [id, waiting] of this.waiting) {
      const state = job.running && job.id === id ? "running" : "queued";
      for (const item of waiting) item.update?.(state);
    }
  }
}
