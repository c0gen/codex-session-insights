import type { WorldId, WorldSnapshot, WorldOptions } from "../data";
import type { SceneFactory } from "../types";
import { referenceFor } from "../references";
import { paper } from "./paper";
import { library } from "./library";
import { trail } from "./trail";
import { reading } from "./reading";
import { vault } from "./vault";
export const factories: Record<WorldId, SceneFactory> = {
  paper,
  library,
  trail,
  reading,
  vault,
};
export function requiredAssets(s: WorldSnapshot, o: WorldOptions): string[] {
  if (o.world === "paper") {
    const id = referenceFor(s.values?.stack_meters ?? 0, o.landmark).id;
    return id === "earth" ? [] : [id];
  }
  return {
    library: ["shelf", "book-blue", "book-red", "book-green"],
    trail: ["person"],
    reading: ["desk", "chair", "bay"],
    vault: ["floppy", "storage-box", "shelf"],
  }[o.world];
}
