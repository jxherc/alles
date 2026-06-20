// decide what the shell shows at boot. pure so it's unit-testable (node).
//   reachable     — did /api/auth/me actually answer (server up)?
//   authenticated — do we have a usable (live or cached) session?
// server down + no cached session => say so, don't dump the user on a dead login wall.
export function chooseBootState(reachable, authenticated) {
  if (authenticated) return "boot"; // cached session keeps the installed PWA usable offline
  if (!reachable) return "notrunning"; // can't reach the server and nothing cached
  return "login"; // server's up, just not signed in here
}
