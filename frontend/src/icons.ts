const paths: Record<string, string> = {
  terminal: '<path d="m5 6 5 6-5 6m8 0h6"/>',
  home: '<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3z"/>',
  chart: '<path d="M3 21h18M6 18V9m6 9V3m6 15v-6"/>',
  folder: '<path d="M3 5h6l2 3h10v13H3z"/>',
  database:
    '<ellipse cx="12" cy="5" rx="9" ry="4"/><path d="M3 5v14c0 5 18 5 18 0V5M3 12c0 5 18 5 18 0"/>',
  refresh: '<path d="M20 7v5h-5M20 12a8 8 0 1 0-2 6"/>',
  file: '<path d="M5 2h9l5 5v15H5zM14 2v6h5M8 12h8m-8 4h8"/>',
  book: '<path d="M12 4v18M12 4C8 1 2 3 2 3v17s6-2 10 2c4-4 10-2 10-2V3s-6-2-10 1"/>',
  ruler: '<path d="m2 17 15-15 5 5L7 22zM6 13l2 2m2-6 2 2m2-6 2 2"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 5v7l5 3"/>',
  flag: '<path d="M4 22V2l8 2 8-2v12l-8 2-8-2"/>',
  money:
    '<circle cx="12" cy="12" r="10"/><path d="M12 5v14m4-11c-5-5-10 4-4 4s1 9-4 4"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="17" rx="2"/><path d="M7 2v6m10-6v6M3 11h18"/>',
  flame:
    '<path d="M12 2c3 7-2 6 0 11 3-2 4-4 4-6 8 9 6 16-4 16S1 15 6 10c0 5 4 6 3 0 0-3 1-6 3-8z"/>',
  laptop: '<path d="M5 3h14v14H5zM2 21h20l-3-4H5z"/>',
  shield: '<path d="m12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6zM12 7v6m0 4h.01"/>',
  settings:
    '<path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/><circle cx="12" cy="12" r="6"/>',
  plus: '<path d="M12 3v18M3 12h18"/>',
  download: '<path d="M12 2v14m-5-5 5 5 5-5M3 17v5h18v-5"/>',
  upload: '<path d="M12 16V2m-5 5 5-5 5 5M3 17v5h18v-5"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-10h.01"/>',
  arrow: '<path d="m8 4 8 8-8 8"/>',
  chevron: '<path d="m5 9 7 7 7-7"/>',
  close: '<path d="m5 5 14 14M5 19 19 5"/>',
};
export const icon = (name: string, size = 20) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
