import type { SceneFactory } from "../types";
import { collectionScene } from "./collection";
export const library: SceneFactory = (s, _o, assets) =>
  collectionScene("library", s.values?.novels ?? 0, assets);
