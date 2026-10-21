import type { Dashboard } from '../types';
import type { EquivalentBasis } from '../text-equivalents-data';
import type { WorldsGallery } from './gallery';

/** Loading a dashboard must not parse Three.js or the embedded model library. */
export class LazyWorldsGallery {
  private gallery?: WorldsGallery;
  private pending?: Promise<void>;
  private active = false;
  private loading = false;
  private latest?: [Dashboard, EquivalentBasis, (basis: EquivalentBasis) => void];
  constructor(private notify: (message: string, error?: boolean) => void) {}
  render() { return this.gallery?.render() ?? '<div id="worlds-host"><p role="status">Loading visualizations…</p></div>'; }
  detach(keep: boolean) { this.active = keep; this.gallery?.detach(keep); }
  mount(data: Dashboard, basis: EquivalentBasis, change: (basis: EquivalentBasis) => void) {
    this.active = true;
    this.latest = [data, basis, change];
    if (this.gallery) { this.gallery.mount(data, basis, change); return; }
    if (!this.pending) this.pending = import('./gallery').then(({ WorldsGallery }) => {
      this.gallery = new WorldsGallery(this.notify);
      this.gallery.setLoading(this.loading);
      if (this.active && this.latest) {
        document.getElementById('worlds-host')?.replaceChildren();
        this.gallery.mount(...this.latest);
      }
    }).catch(() => {
      this.notify('Could not load visualizations. Open the page again to retry.', true);
    }).finally(() => { this.pending = undefined; });
  }
  update(data: Dashboard, basis: EquivalentBasis) {
    if (this.latest) this.latest = [data, basis, this.latest[2]];
    this.gallery?.update(data, basis);
  }
  setLoading(value: boolean) { this.loading = value; this.gallery?.setLoading(value); }
}
