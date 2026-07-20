// All upsell / sign-up CTAs route anonymous local-viewer users to the public
// cloud sign-up. Open in a new tab so the local results stay put.
export const SIGNUP_URL = "https://app.strix.ai/api/auth/signup";
export const DEMO_URL = "https://strix.ai/demo";
export const PRICING_URL = "https://strix.ai/pricing";

// Best-effort, anonymous conversion tracking. The local server forwards this to
// PostHog only if the user has telemetry enabled; it never blocks navigation.
export function trackCta(cta: string): void {
  try {
    const body = JSON.stringify({ event: "cta_clicked", cta });
    if (typeof navigator !== "undefined" && navigator.sendBeacon) {
      navigator.sendBeacon("/api/event", body);
    } else {
      void fetch("/api/event", { method: "POST", body, keepalive: true });
    }
  } catch {
    /* analytics is best-effort */
  }
}
