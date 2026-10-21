import { Box3, Vector3 } from "three";

export const BOOKS_PER_CASE = 150,
  DISKS_PER_CASE = 100,
  CASES_PER_RACK = 20;
export const SECTION_CASES = 64,
  SECTION_WIDTH = 12,
  SECTION_DEPTH = 8.6;
export function occupancy(total: number, capacity = 1) {
  const nearest = Math.round(total),
    tolerance = Math.max(1, total) * Number.EPSILON * 4;
  const value = Math.abs(nearest - total) < tolerance ? nearest : total;
  const full = Math.floor(value / capacity),
    remainder = value - full * capacity;
  return { full, remainder, count: full + (remainder > 0 ? 1 : 0) };
}
/** Morton sections extend in a stable square layout; existing shelves never move. */
export function sectionPosition(index: number): [number, number] {
  let x = 0,
    z = 0,
    bit = 1;
  while (index > 0) {
    const q = index % 4;
    x += (q % 2) * bit;
    z += Math.floor(q / 2) * bit;
    index = Math.floor(index / 4);
    bit *= 2;
  }
  return [x, z];
}
export class CollectionLayout {
  count: number;
  side: number;
  bounds: Box3;
  constructor(
    readonly total: number,
    readonly capacity: number,
  ) {
    this.count = occupancy(total, capacity).count;
    this.side =
      2 **
      Math.ceil(
        Math.log2(
          Math.max(1, Math.ceil(Math.sqrt(Math.ceil(this.count / 64)))),
        ),
      );
    this.bounds = new Box3();
    this.sections((start, side, x, z) => {
      const end = Math.min(this.count, start + side * side * 64);
      if (side === 1 && end - start < 64) {
        for (let i = start; i < end; i++) this.bounds.union(this.caseBounds(i));
      } else this.bounds.union(this.sectionBounds(side, x, z));
    }, 32);
    if (this.bounds.isEmpty())
      this.bounds.set(new Vector3(-0.7, 0, -0.3), new Vector3(0.7, 1.8, 0.3));
  }
  amount(index: number) {
    return Math.max(
      0,
      Math.min(this.capacity, this.total - index * this.capacity),
    );
  }
  position(index: number) {
    const [x, z] = sectionPosition(Math.floor(index / 64)),
      slot = index % 64;
    return {
      x: x * 12 + (Math.floor(slot / 2) % 8) * 1.38,
      z: z * 8.6 + Math.floor(slot / 16) * 1.85 + (slot % 2 ? -0.16 : 0.16),
      rotation: slot % 2 ? Math.PI : 0,
    };
  }
  caseBounds(index: number) {
    const p = this.position(index);
    return new Box3(
      new Vector3(p.x - 0.66, 0, p.z - 0.15),
      new Vector3(p.x + 0.66, 1.8, p.z + 0.15),
    );
  }
  sectionBounds(side: number, x: number, z: number) {
    return new Box3(
      new Vector3(x * 12 - 0.66, 0, z * 8.6 - 0.31),
      new Vector3(
        (x + side - 1) * 12 + 10.32,
        1.8,
        (z + side - 1) * 8.6 + 5.86,
      ),
    );
  }
  /** Emits a bounded partition, with exact ranges even in the final incomplete section. */
  sections(
    visit: (start: number, side: number, x: number, z: number) => void,
    limit = 64,
  ) {
    const walk = (start: number, side: number, x: number, z: number) => {
      if (start >= this.count) return;
      const full = start + side * side * 64 <= this.count;
      if (
        side === 1 ||
        (full && side * side <= Math.max(1, (this.side * this.side) / limit))
      ) {
        visit(start, side, x, z);
        return;
      }
      const half = side / 2,
        step = half * half * 64;
      for (let q = 0; q < 4; q++)
        walk(
          start + q * step,
          half,
          x + (q % 2) * half,
          z + Math.floor(q / 2) * half,
        );
    };
    walk(0, this.side, 0, 0);
  }
  map() {
    const cells: {
      x: number;
      z: number;
      width: number;
      depth: number;
      index: number;
      count: number;
    }[] = [];
    this.sections((start, side, x, z) => {
      if (side === 1 && this.count <= 64)
        for (let i = start; i < Math.min(this.count, start + 64); i++) {
          const p = this.position(i);
          cells.push({
            x: p.x - 0.66,
            z: p.z - 0.15,
            width: 1.32,
            depth: 0.3,
            index: i,
            count: 1,
          });
        }
      else {
        const b = this.sectionBounds(side, x, z);
        cells.push({
          x: b.min.x,
          z: b.min.z,
          width: b.max.x - b.min.x,
          depth: b.max.z - b.min.z,
          index: start,
          count: Math.min(this.count - start, side * side * 64),
        });
      }
    });
    return {
      x: this.bounds.min.x,
      z: this.bounds.min.z,
      width: this.bounds.max.x - this.bounds.min.x,
      depth: this.bounds.max.z - this.bounds.min.z,
      cells,
    };
  }
}
