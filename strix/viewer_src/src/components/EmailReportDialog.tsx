import { useEffect, useRef, useState } from "react";
import { X, Mail, ShieldCheck, Lock, Copy, Check, Loader2, AlertCircle } from "lucide-react";
import {
  otpStart,
  otpVerify,
  sendReport,
  type AuthStatus,
} from "@/data/serverSource";

type Step = "disclosure" | "email" | "code" | "sending" | "password";

/**
 * "report" runs the full disclosure -> verify -> encrypted send flow.
 * "verify" is a verify-only flow (view past runs): it starts at the email step
 * and finishes as soon as the code is confirmed, without sending a report.
 */
type Purpose = "report" | "verify";

interface EmailReportDialogProps {
  open: boolean;
  onClose: () => void;
  activeRun: string | null;
  auth: AuthStatus | null;
  purpose: Purpose;
  /** Re-fetch auth status after a successful verify (lifts state to App). */
  onVerified: () => void;
}

const OTP_START_ERRORS: Record<string, string> = {
  rate_limited: "Too many requests. Wait a minute and try again.",
  invalid_email: "That email does not look right. Check it and try again.",
  work_email_required: "Please use your work email, not a personal one.",
  unavailable: "The email service is unavailable right now. Try again shortly.",
};

// Small common set for instant UX only; the relay is authoritative on the full
// free/personal domain list.
const COMMON_FREE_DOMAINS = new Set([
  "gmail.com",
  "googlemail.com",
  "yahoo.com",
  "ymail.com",
  "outlook.com",
  "hotmail.com",
  "live.com",
  "icloud.com",
  "me.com",
  "aol.com",
  "proton.me",
  "protonmail.com",
  "gmx.com",
  "mail.com",
]);

function isCommonFreeEmail(email: string): boolean {
  const domain = email.split("@")[1]?.trim().toLowerCase();
  return domain != null && COMMON_FREE_DOMAINS.has(domain);
}

const SEND_ERRORS: Record<string, string> = {
  forbidden: "This email was unsubscribed from Strix, so we cannot send to it.",
  too_large: "This report is too large to email. Try a smaller run.",
  unavailable: "The email service is unavailable right now. Try again shortly.",
};

export default function EmailReportDialog({
  open,
  onClose,
  activeRun,
  auth,
  purpose,
  onVerified,
}: EmailReportDialogProps) {
  const verified = auth?.verified === true;
  const [step, setStep] = useState<Step>("disclosure");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [filename, setFilename] = useState("");
  const [copied, setCopied] = useState(false);
  const sentTo = useRef<string>("");

  // Reset each time the dialog opens. The report flow opens on the disclosure
  // step; the verify-only flow skips it and starts straight at the email step.
  // Prefill the email when already verified so the flow can skip ahead.
  useEffect(() => {
    if (!open) return;
    setStep(purpose === "verify" ? "email" : "disclosure");
    setCode("");
    setBusy(false);
    setError(null);
    setNotice(null);
    setPassword("");
    setFilename("");
    setCopied(false);
    setEmail(auth?.email ?? "");
  }, [open, auth?.email, purpose]);

  // Close on Escape (but never while a password is on screen: it must not be
  // dismissed by accident).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && step !== "password") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, step, onClose]);

  if (!open) return null;

  const doSend = async () => {
    setStep("sending");
    setError(null);
    const result = await sendReport(activeRun);
    if (result.ok) {
      setPassword(result.password);
      setFilename(result.filename);
      setStep("password");
      return;
    }
    // A stale session needs a fresh OTP; unverified means we never had one.
    if (result.error === "reverify" || result.error === "unverified") {
      setNotice("Your verification expired. Enter your email to verify again.");
      setStep("email");
      return;
    }
    setError(SEND_ERRORS[result.error] ?? "Could not send the report. Try again.");
    setStep("disclosure");
  };

  const startFlow = () => {
    setError(null);
    setNotice(null);
    if (verified) {
      void doSend();
    } else {
      setStep("email");
    }
  };

  const submitEmail = async () => {
    const value = email.trim();
    if (!value) {
      setError("Enter your email to continue.");
      return;
    }
    // Snappy client-side guard for the obvious personal domains; the relay is
    // still authoritative on the full list.
    if (isCommonFreeEmail(value)) {
      setError(OTP_START_ERRORS.work_email_required);
      return;
    }
    setBusy(true);
    setError(null);
    const result = await otpStart(value);
    setBusy(false);
    if (result.ok) {
      setNotice(`We sent a 6-digit code to ${value}.`);
      setStep("code");
    } else {
      setError(OTP_START_ERRORS[result.error] ?? "Could not send a code. Try again.");
    }
  };

  const submitCode = async () => {
    const value = code.trim();
    if (value.length < 4) {
      setError("Enter the 6-digit code from your email.");
      return;
    }
    setBusy(true);
    setError(null);
    const result = await otpVerify(email.trim(), value);
    setBusy(false);
    if (result.verified) {
      sentTo.current = result.email;
      onVerified();
      // Verify-only flow (viewing past runs) stops here; no report is sent.
      if (purpose === "verify") {
        onClose();
        return;
      }
      void doSend();
    } else {
      setError("That code did not match. Check it and try again.");
    }
  };

  const copyPassword = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard may be unavailable; the password is visible to copy manually */
    }
  };

  const confirmationEmail = sentTo.current || auth?.email || email.trim();

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Email an encrypted report"
    >
      <div
        className="absolute inset-0 bg-black/70"
        onClick={() => step !== "password" && onClose()}
      />
      <div
        className="relative z-10 w-full max-w-md rounded-2xl bg-[#0a0a0a] p-6 shadow-2xl"
        style={{ border: "1px solid #2a2a2a" }}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 cursor-pointer text-[#666] transition-colors hover:text-white"
          aria-label="Close"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="mb-4 flex items-center gap-2.5">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-lg"
            style={{ border: "1px solid #2a2a2a", background: "rgba(255,255,255,0.04)" }}
          >
            <Mail className="h-4 w-4 text-emerald-400" aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-white">
              {purpose === "verify"
                ? "Verify your email to view your runs"
                : "Email an encrypted PDF report of this run"}
            </h2>
            <p className="text-xs text-[#666]">
              {purpose === "verify"
                ? "We send a one-time code to confirm it is you."
                : "Verified by a one-time code sent to your email"}
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2">
            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-400" aria-hidden="true" />
            <p className="text-xs text-red-300">{error}</p>
          </div>
        )}
        {notice && !error && step !== "password" && (
          <p className="mb-4 text-xs text-[#888]">{notice}</p>
        )}

        {step === "disclosure" && (
          <div className="space-y-4">
            <div
              className="space-y-2.5 rounded-lg p-3.5"
              style={{ border: "1px solid #222", background: "rgba(255,255,255,0.02)" }}
            >
              <div className="flex items-start gap-2.5">
                <ShieldCheck className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-400" aria-hidden="true" />
                <p className="text-xs leading-relaxed text-[#aaa]">
                  Viewing stays local and nothing is uploaded. Emailing is an explicit
                  opt-in: we send an <span className="text-white">encrypted PDF</span>.
                </p>
              </div>
              <div className="flex items-start gap-2.5">
                <Lock className="mt-0.5 h-4 w-4 flex-shrink-0 text-[#888]" aria-hidden="true" />
                <p className="text-xs leading-relaxed text-[#aaa]">
                  The report is encrypted with a password that only you hold. Strix
                  cannot read it and never stores it. We collect only your email so we
                  can send it.
                </p>
              </div>
            </div>
            <button
              onClick={startFlow}
              className="w-full cursor-pointer rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-black transition-opacity hover:opacity-90"
            >
              {verified ? "Email me the encrypted PDF" : "Continue with your email"}
            </button>
            {verified && auth?.email && (
              <p className="text-center text-xs text-[#666]">Sending to {auth.email}</p>
            )}
          </div>
        )}

        {step === "email" && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void submitEmail();
            }}
          >
            <label className="block">
              <span className="mb-1.5 block text-xs text-[#888]">Your email</span>
              <input
                type="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="w-full rounded-lg bg-black px-3 py-2.5 text-sm text-white outline-none transition-colors focus:border-[#444]"
                style={{ border: "1px solid #2a2a2a" }}
              />
              <span className="mt-1.5 block text-xs text-[#666]">Use your work email.</span>
            </label>
            <button
              type="submit"
              disabled={busy}
              className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-black transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              Send me a code
            </button>
          </form>
        )}

        {step === "code" && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void submitCode();
            }}
          >
            <label className="block">
              <span className="mb-1.5 block text-xs text-[#888]">6-digit code</span>
              <input
                inputMode="numeric"
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="123456"
                className="w-full rounded-lg bg-black px-3 py-2.5 text-center text-lg font-mono tracking-[0.4em] text-white outline-none transition-colors focus:border-[#444]"
                style={{ border: "1px solid #2a2a2a" }}
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-black transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {purpose === "verify" ? "Verify" : "Verify and send"}
            </button>
            <button
              type="button"
              onClick={() => {
                setStep("email");
                setError(null);
                setNotice(null);
              }}
              className="w-full cursor-pointer text-center text-xs text-[#666] transition-colors hover:text-[#aaa]"
            >
              Use a different email
            </button>
          </form>
        )}

        {step === "sending" && (
          <div className="flex flex-col items-center gap-3 py-8">
            <Loader2 className="h-6 w-6 animate-spin text-white" aria-hidden="true" />
            <p className="text-sm text-[#aaa]">Generating and encrypting locally...</p>
          </div>
        )}

        {step === "password" && (
          <div className="space-y-4">
            <div className="flex items-start gap-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5">
              <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-400" aria-hidden="true" />
              <p className="text-xs text-emerald-200">
                Sent to {confirmationEmail}. Open the attached PDF with this password.
              </p>
            </div>
            <div>
              <span className="mb-1.5 block text-xs text-[#888]">Your one-time password</span>
              <div
                className="flex items-center gap-2 rounded-lg bg-black p-3"
                style={{ border: "1px solid #2a2a2a" }}
              >
                <code className="flex-1 break-all font-mono text-base text-white">{password}</code>
                <button
                  onClick={copyPassword}
                  className="flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-xs text-[#aaa] transition-colors hover:bg-[rgba(255,255,255,0.06)] hover:text-white"
                  style={{ border: "1px solid #2a2a2a" }}
                >
                  {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="mt-2 text-xs text-[#666]">
                Save this now. Strix never stores it, so we cannot show it again. File:{" "}
                <span className="font-mono text-[#888]">{filename}</span>
              </p>
            </div>
            <button
              onClick={onClose}
              className="w-full cursor-pointer rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[rgba(255,255,255,0.06)]"
              style={{ border: "1px solid #2a2a2a" }}
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
