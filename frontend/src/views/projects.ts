import { icon } from "../icons";
import { compact, currency } from "../charts";
import { esc, count, dateLabel, tip, button, segment } from "../ui";
import { kpis } from "../components";
import type { Dashboard } from "../types";
export function projects(data: Dashboard) {
  return `<section class="panel projects-panel"><div class="panel-heading"><div><h2>Your projects</h2><p>${data.projects.length} projects in this view · select one to explore</p></div><input id="project-search" class="search" placeholder="Find a project…" aria-label="Find a project"></div><div class="table-scroll"><table><thead><tr><th>Project</th><th>Chats</th><th>Tokens</th><th>Est. cost</th><th>Observed lines</th><th>Last active</th><th></th></tr></thead><tbody>${data.projects.map((p) => `<tr data-project="${esc(p.project_id)}"><td><span class="project-name">${icon("folder", 18)}${esc(p.name)}</span></td><td>${count(p.chats)}</td><td>${compact(p.tokens)}</td><td>${currency(p.cost)}</td><td><span class="positive">+${compact(p.added)}</span> <span class="negative">−${compact(p.removed)}</span></td><td>${dateLabel(p.last_active)}</td><td><button class="icon-button merge-project" data-id="${esc(p.project_id)}" title="Merge with another project">${icon("settings", 17)}</button></td></tr>`).join("")}</tbody></table></div>${!data.projects.length ? '<div class="empty-state">No projects in this range.</div>' : ""}</section>`;
}
