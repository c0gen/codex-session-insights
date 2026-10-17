import "./project-merges.css";
import type { Dashboard, JobCompletion, ProjectMerge } from "./types";
import { esc } from "./ui";

type Submit = (action: string, args: unknown, state: (state: "queued" | "running") => void) => Promise<JobCompletion | null>;
type Dialog = (title: string, body: string, footer: string, bind: () => void) => void;

/** Selection and search outlive dashboard redraws. The modal owns its draft. */
export class ProjectMerges {
  readonly selected = new Set<string>();
  search = "";
  private pending = false;
  private message = "";
  private failed = false;
  private last?: ProjectMerge | null;

  constructor(private submit: Submit, private dialog: Dialog, private close: () => void) {}

  bind(data: Dashboard) {
    this.last = data.project_merge;
    const ids = new Set(data.options.projects.map(p => p.id));
    for (const id of this.selected) if (!ids.has(id)) this.selected.delete(id);
    const root = document.querySelector<HTMLElement>(".projects-panel");
    if (!root) return;
    const search = root.querySelector<HTMLInputElement>("#project-search")!;
    search.value = this.search;
    const applySearch = () => {
      for (const row of Array.from(root.querySelectorAll<HTMLTableRowElement>("tr[data-project]"))) {
        row.hidden = !row.textContent!.toLocaleLowerCase().includes(this.search.toLocaleLowerCase());
      }
      this.controls(data);
    };
    search.oninput = () => { this.search = search.value; applySearch(); };
    for (const checkbox of Array.from(root.querySelectorAll<HTMLInputElement>("[data-select-project]"))) {
      checkbox.checked = this.selected.has(checkbox.dataset.selectProject!);
      checkbox.onchange = () => {
        const id = checkbox.dataset.selectProject!;
        if (checkbox.checked) this.selected.add(id); else this.selected.delete(id);
        this.controls(data);
      };
    }
    root.querySelector<HTMLInputElement>("#select-visible-projects")!.onchange = (event) => {
      const checked = (event.target as HTMLInputElement).checked;
      for (const checkbox of Array.from(root.querySelectorAll<HTMLInputElement>("tr:not([hidden]) [data-select-project]"))) {
        checkbox.checked = checked;
        if (checked) this.selected.add(checkbox.dataset.selectProject!); else this.selected.delete(checkbox.dataset.selectProject!);
      }
      this.controls(data);
    };
    root.querySelector<HTMLButtonElement>("#merge-selected")!.onclick = () => this.open(data, [...this.selected]);
    root.querySelector<HTMLButtonElement>("#undo-project-merge")!.onclick = () => { void this.undo(data); };
    root.querySelectorAll<HTMLButtonElement>(".merge-project").forEach(button => {
      button.onclick = () => this.open(data, [button.dataset.id!]);
    });
    applySearch();
  }

  private controls(data: Dashboard) {
    const root = document.querySelector<HTMLElement>(".projects-panel");
    if (!root) return;
    const blocked = this.pending || !!data.readonly || !!data.project_migration_pending;
    root.querySelectorAll<HTMLInputElement>("[data-select-project],#select-visible-projects").forEach(input => input.disabled = blocked);
    root.querySelectorAll<HTMLButtonElement>(".merge-project").forEach(button => button.disabled = blocked || data.options.projects.length < 2);
    const bulk = root.querySelector<HTMLButtonElement>("#merge-selected")!;
    bulk.disabled = blocked || !this.selected.size || data.options.projects.length < 2;
    root.querySelector("#project-selection-count")!.textContent = `${this.selected.size} selected`;
    const undo = root.querySelector<HTMLButtonElement>("#undo-project-merge")!;
    undo.hidden = !this.last;
    undo.disabled = blocked;
    undo.title = this.last ? `Undo merge into ${this.last.target.name}` : "";
    const visible = Array.from(root.querySelectorAll<HTMLInputElement>("tr:not([hidden]) [data-select-project]"));
    const all = root.querySelector<HTMLInputElement>("#select-visible-projects")!;
    all.checked = visible.length > 0 && visible.every(input => input.checked);
    all.indeterminate = !all.checked && visible.some(input => input.checked);
    const status = root.querySelector<HTMLElement>("#project-merge-status")!;
    status.textContent = data.project_migration_pending ? "Recovering original project identities… Merge will be available when this finishes." : this.message;
    status.classList.toggle("error", this.failed);
  }

  private open(data: Dashboard, selected: string[]) {
    if (this.pending) return;
    const options = data.options.projects;
    let target = selected.length > 1 ? selected[0] : options.find(p => p.id !== selected[0])?.id || "";
    this.dialog("Merge project groups",
      `<p>Group analytics under one retained project name. All usage totals stay the same.</p>
       <label>Find a destination<input type="search" id="merge-search" placeholder="Search project names…" autocomplete="off"></label>
       <div id="merge-destinations" class="merge-destinations" role="group" aria-label="Destination projects"></div>
       <div id="merge-preview" class="merge-preview"></div><p id="merge-feedback" role="status"></p>`,
      '<button id="merge-save" class="button primary">Merge groups</button>', () => {
        const search = document.querySelector<HTMLInputElement>("#merge-search")!;
        const list = document.querySelector<HTMLElement>("#merge-destinations")!;
        const save = document.querySelector<HTMLButtonElement>("#merge-save")!;
        const modal = save.closest<HTMLElement>('[role="dialog"]')!;
        const preview = () => {
          const destination = options.find(p => p.id === target);
          const sources = options.filter(p => selected.includes(p.id) && p.id !== target);
          document.querySelector("#merge-preview")!.innerHTML = `<strong>Retained name: ${esc(destination?.name || "Choose a destination")}</strong><p>Source groups (${sources.length}): ${sources.map(p => esc(p.name)).join(", ") || "Select a different destination to merge this group."}</p>`;
          save.disabled = this.pending || !destination || !sources.length;
        };
        const destinations = () => {
          const query = search.value.toLocaleLowerCase();
          const matches = options.filter(p => p.name.toLocaleLowerCase().includes(query));
          list.innerHTML = matches.map(p => `<label class="merge-destination"><input type="radio" name="merge-destination" value="${esc(p.id)}" ${target === p.id ? "checked" : ""}><span>${esc(p.name)}${selected.includes(p.id) ? ' <small>selected group</small>' : ""}</span></label>`).join("") || '<p class="fine-print">No matching projects.</p>';
          list.querySelectorAll<HTMLInputElement>("input").forEach(input => input.onchange = () => { target = input.value; preview(); });
          preview();
        };
        search.oninput = destinations;
        save.onclick = async () => {
          if (this.pending || save.disabled) return;
          this.pending = true;
          save.disabled = true;
          search.disabled = true;
          list.querySelectorAll<HTMLInputElement>("input").forEach(input => input.disabled = true);
          this.failed = false;
          this.controls(data);
          const feedback = document.querySelector<HTMLElement>("#merge-feedback")!;
          const result = await this.submit("merge_projects", { sources: selected, target }, state => {
            this.message = state === "queued" ? "Merge queued…" : "Merging project groups…";
            feedback.textContent = this.message;
            this.controls(data);
          });
          this.pending = false;
          if (result?.state === "completed") {
            const merge = result.result as unknown as ProjectMerge;
            this.last = merge;
            this.selected.clear();
            this.message = `Merged ${merge.sources.length} source groups into ${merge.target.name}. Undo last merge is available.`;
            if (modal.isConnected) this.close();
          } else {
            this.failed = true;
            this.message = result?.error || "Merge failed. Refresh projects and retry.";
            if (feedback.isConnected) {
              feedback.textContent = this.message;
              feedback.classList.add("error");
              search.disabled = false;
              destinations();
            }
          }
          this.controls(data);
        };
        destinations();
      });
  }

  private async undo(data: Dashboard) {
    if (this.pending || !this.last) return;
    this.pending = true;
    this.failed = false;
    this.controls(data);
    const result = await this.submit("undo_project_merge", { operation_id: this.last.operation_id }, state => {
      this.message = state === "queued" ? "Undo queued…" : "Restoring project groups…";
      this.controls(data);
    });
    this.pending = false;
    this.failed = result?.state !== "completed";
    this.message = this.failed ? result?.error || "Undo failed. Refresh projects and retry." : "Last merge undone. Project groups restored, including new chats.";
    if (!this.failed) this.last = null;
    this.controls(data);
  }
}
