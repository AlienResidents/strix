import { useCallback, useState } from "react";
import { Send } from "lucide-react";
import { steerAgent } from "@/data/serverSource";
import { track } from "@/lib/cta";

/**
 * Send a live instruction to one specific running agent. Only rendered when the
 * viewer runs in-process during a live scan (steering available). Reused by the
 * Agents graph composer and the per-agent detail modal, so both steer through
 * the same path.
 */
export function AgentSteerInput({
  agentId,
  agentName,
  placeholder = "e.g. Focus on the authentication flow next",
}: {
  agentId: string;
  agentName: string;
  placeholder?: string;
}) {
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const send = useCallback(async () => {
    const text = message.trim();
    if (!text || sending) return;
    setSending(true);
    setFeedback(null);
    const res = await steerAgent(agentId, text);
    setSending(false);
    if (res.ok) {
      setMessage("");
      setFeedback(`Sent to ${agentName}`);
      track("agent_steered");
    } else if (res.error === "not_delivered") {
      setFeedback("Could not reach that agent (it may have finished).");
    } else {
      setFeedback("Could not send that message. Try again.");
    }
  }, [message, sending, agentId, agentName]);

  return (
    <div className="w-full">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={placeholder}
          maxLength={4000}
          disabled={sending}
          className="flex-1 min-w-0 rounded-lg border border-[#2a2a2a] bg-[rgba(255,255,255,0.03)] px-3 py-2 text-sm text-white placeholder:text-[#555] focus:outline-none focus:border-[#3a3a3a] disabled:opacity-50"
        />
        <button
          onClick={() => void send()}
          disabled={sending || !message.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          <Send className="w-3.5 h-3.5" aria-hidden="true" />
          {sending ? "Sending" : "Send"}
        </button>
      </div>
      {feedback && <p className="mt-2 text-xs text-[#888]">{feedback}</p>}
    </div>
  );
}

export default AgentSteerInput;
