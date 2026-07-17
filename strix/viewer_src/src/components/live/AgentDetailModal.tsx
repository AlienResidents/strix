import { useEffect } from "react";
import { X } from "lucide-react";
import { AgentTranscript } from "./AgentTranscript";
import type { TranscriptAgent, TranscriptEvent } from "@/data/serverSource";

/**
 * Overlay modal showing a single agent's full transcript. Matches the cloud
 * app, where clicking a node in the agent graph opens a modal (rather than
 * revealing a section beneath the graph). Closes on backdrop click, the X
 * button, or Escape.
 */
export function AgentDetailModal({
  agent,
  events,
  onClose,
}: {
  agent: TranscriptAgent;
  events: TranscriptEvent[];
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:p-8"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Agent ${agent.name}`}
    >
      <div
        className="relative my-auto w-full max-w-3xl rounded-xl border border-[#222] bg-[#0a0a0a] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-3 top-3 z-10 rounded-md p-1 text-[#888] transition-colors hover:bg-[#1a1a1a] hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="max-h-[85vh] overflow-y-auto p-5">
          <AgentTranscript agent={agent} events={events} />
        </div>
      </div>
    </div>
  );
}

export default AgentDetailModal;
