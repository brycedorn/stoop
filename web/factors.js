/* Factor groups, icons and rank weights: shared by the map (app.js) and the ranking page (rank.js). */
(function () {
  "use strict";
  // Factor groups: the tag color says which group, the icon says which factor, the text says it in words.
  // Three hues only: dataviz's categorical slots 1-3 are the set that passes all-pairs (validate_palette.js
  // --pairs all, light and dark); a fourth hue fails, so the fourth group is neutral ink.
  const GROUPS = [
    { id: "cost", title: "Cost & space", keys: ["rent", "size", "space"], color: { light: "#2a78d6", dark: "#3987e5" } },
    { id: "move", title: "Getting around", keys: ["commute", "airports", "citibike", "errands"], color: { light: "#eb6834", dark: "#d95926" } },
    { id: "life", title: "Lifestyle & outdoors", keys: ["running", "gym", "dogs", "green", "favorites", "familiarity"], color: { light: "#1baf7a", dark: "#199e70" } },
    { id: "env", title: "Safety & environment", keys: ["safety", "quiet", "air"], color: { light: "#6f6d68", dark: "#9a988f" } },
  ];
  const OTHER = { id: "other", title: "Other", keys: [], color: { light: "#6f6d68", dark: "#9a988f" } };
  // 24px stroke icons, one per factor (shape carries identity alongside the group color)
  const ICON_PATHS = {
    dogs: "M6 10.5H15C15.2 8 15.8 6 17 6H19.5L21.5 7.5V8.5L19 9.5C18.6 10.5 18.5 11.5 18.5 12.5V19.5H17V14.5H8.5V19.5H7V14C6.3 13 6 12 6 10.5ZM6 10.5C4.5 10 3.6 8.6 3.6 6.5M17.6 6.2L16.9 9M19.4 7.3v.01",
    rent: "M12 3v18M16.5 7H10a3 3 0 0 0 0 6h4a3 3 0 0 1 0 6H7",
    size: "M4 4h16v16H4zM4 12h7v8M15 4v5",
    space: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM16.5 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 20c0-3 2.4-5 5.5-5s5.5 2 5.5 5M13.5 15.3c.9-.2 1.9-.3 3-.3 3.1 0 5 2 5 5",
    commute: "M7 3h10a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3zM4 10h16M8 21l2-4M16 21l-2-4M8.5 13.5h.01M15.5 13.5h.01",
    citibike: "M5.5 18.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM18.5 18.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5.5 15l4-7h5.5l3.5 7M9.5 8 8 5H6M12 15l3-7",
    errands: "M5 8h14l-1.2 12H6.2zM9 8V6.5a3 3 0 0 1 6 0V8",
    running: "M4 19c4.5 0 3.5-7 8-7s3.5-7 8-7M18 3l2 2-2 2",
    green: "M12 22v-5M12 2.5l6 8.5h-3.2l4.2 6H5l4.2-6H6z",
    favorites: "M7 3v7a2 2 0 0 0 4 0V3M9 12v9M17 3c-1.7 1.6-2 5.5 0 7.5V21",
    familiarity: "M12 20s-7.5-4.4-7.5-10A4.2 4.2 0 0 1 12 7.3 4.2 4.2 0 0 1 19.5 10c0 5.6-7.5 10-7.5 10z",
    gym: "M6.5 7v10M17.5 7v10M3.5 9.5v5M20.5 9.5v5M6.5 12h11",
    airports: "M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z",
    bus: "M7 3.5h10A2.5 2.5 0 0 1 19.5 6v10.5h-15V6A2.5 2.5 0 0 1 7 3.5zM4.5 11h15M7.5 20v-3.5M16.5 20v-3.5M8 14h.01M16 14h.01",
    safety: "M12 3l7.5 3v6c0 4.2-3.1 7.4-7.5 9-4.4-1.6-7.5-4.8-7.5-9V6z",
    air: "M3 8h11a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h8",
    quiet: "M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  };
  // Priorities as a ranked list: top counts most, weights fall off down the list
  const RANK_WEIGHTS = [30, 22, 16, 12, 9, 7, 5, 4, 3, 2];
  window.STOOP_UI = { GROUPS, OTHER, ICON_PATHS, RANK_WEIGHTS };
})();
