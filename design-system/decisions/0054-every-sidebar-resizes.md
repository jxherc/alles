# every sidebar resizes

## context

only aide code's projects rail could be dragged wider. the owner: "if the bars are adjustable on
aide it should be adjustable everywhere" (28.05), and later "resizable bars: every app's sidebar".

## decision

- one module, `static/js/rail_resize.js` `makeResizableRail`, lifted from aide code's handle: a
  12px `role="separator"` strip on the rail's trailing edge (32px grab for a finger), pointer drag
  (mouse, pen, touch), arrow keys step 1rem (shift 3), home and end, double click goes back to the
  app's own width. `aria-valuenow` in rem, `aria-valuetext` in px. one look in `kokuen.css`
  (`.k-rail-resize`): a 2px line shows on hover, drag and focus.
- the width is in rem (it grows with the type) and saved per browser under `alles-rail-<app>`.
- used by aide chat's archive, docs, settings, files, mail, calendar and photos (wired in `app.js`),
  and aide code's projects rail.
- rails a module fills with `innerHTML` (mail, calendar, photos, files) keep the handle outside
  them, placed over the edge from the rail's positioned ancestor. static rails (aide's archive,
  docs, settings) hold it inside.
- a sized rail takes `--k-rail-w`; files' grid reads it for its first track.
- below 761px (621px for aide's drawer and aide code) and wherever an app stacks its rail over the
  content, there's no handle and the app's own layout wins.

## checked

webkit at 1280, 820 and 770 wide: every rail drags by mouse, by touch pointer events, by arrow
keys, keeps its width over a reload and goes back on double click; 700 and 390 wide show no handle.
