import {
  EARTH_RADIUS_M,
  SHEET_WIDTH_M,
  SHEET_LENGTH_M,
  type Proportions,
} from "./data";

export const REFERENCES = [
  {
    id: "person",
    name: "Person (assumed)",
    height: 1.75,
    source: "",
    note: "Illustrative adult height",
  },
  {
    id: "house",
    name: "House (assumed)",
    height: 10,
    source: "",
    note: "Illustrative house height",
  },
  {
    id: "eiffel",
    name: "Eiffel Tower",
    height: 330,
    source:
      "https://www.toureiffel.paris/en/news/history-and-culture/300-330-meters-story-towers-height",
    note: "Height including antenna",
  },
  {
    id: "burj",
    name: "Burj Khalifa",
    height: 828,
    source: "https://www.burjkhalifa.ae/img/FACT-SHEET.pdf",
    note: "Architectural height",
  },
  {
    id: "everest",
    name: "Everest summit elevation",
    height: 8848.86,
    source:
      "https://science.nasa.gov/earth/earth-observatory/himalayas-near-and-far-147980/",
    note: "Above sea level; schematic terrain",
  },
  {
    id: "earth",
    name: "Earth diameter (spherical model)",
    height: EARTH_RADIUS_M * 2,
    source: "https://science.nasa.gov/moon/by-the-numbers/",
    note: "Mean radius 6,371 km",
  },
] as const;
export type Reference = (typeof REFERENCES)[number];
export function referenceFor(height: number, choice: string): Reference {
  const selected = REFERENCES.find((r) => r.id === choice);
  if (selected) return selected;
  const index =
    height < 4
      ? 0
      : height < 70
        ? 1
        : height < 500
          ? 2
          : height < 3000
            ? 3
            : height < 100000
              ? 4
              : 5;
  return REFERENCES[index];
}
export function paperLayout(
  height: number,
  proportions: Proportions,
  choice = "auto",
) {
  const reference = referenceFor(height, choice);
  // Tabletop-scale towers need no skyscraper-sized framing.
  const showReference = height >= 0.2 || choice !== "auto";
  const unit = Math.max(height, showReference ? reference.height : 0, 0.3);
  const enlargement =
    proportions === "true" ? 1 : Math.max(1, (height * 0.06) / SHEET_WIDTH_M);
  return {
    reference,
    showReference,
    unit,
    height: height / unit,
    width: (SHEET_WIDTH_M * enlargement) / unit,
    depth: (SHEET_LENGTH_M * enlargement) / unit,
    enlargement,
  };
}
