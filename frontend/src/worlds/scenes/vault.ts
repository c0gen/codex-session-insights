import type { SceneFactory } from "../types";
import { collectionScene } from "./collection";
export const vault: SceneFactory = (s, _o, assets) =>
  collectionScene("vault", s.values?.floppy_disks ?? 0, assets);
