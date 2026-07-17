// Slim, dependency-free extract of strix-app's display-number helper. The full
// version queries Supabase to compute org-wide finding numbers; the local viewer
// only ever needs the pure formatter, so the supabase-backed functions are
// intentionally omitted (a local run has no org context).
export function formatStrixId(num: number): string {
  return `STRIX-${num}`;
}
