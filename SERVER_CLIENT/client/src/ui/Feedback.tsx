import { useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import "./feedback.css";

let origin: HTMLElement | null = null;
if (typeof document !== "undefined") {
  const remember = (event: Event) => {
    if (event.target instanceof Element && !event.target.closest(".ui-feedback")) {
      const candidate = event.target.closest<HTMLElement>("button,input,select,textarea,summary,a");
      if (candidate?.getClientRects().length) origin = candidate;
    }
  };
  for (const name of ["click", "input", "change"]) document.addEventListener(name, remember, true);
}

/** Persistent, in-flow feedback beside the initiating controls, including dialogs. */
export default function Feedback({ message, kind = "error", onDismiss, className = "", scope }: {
  message: string | null | undefined;
  kind?: "error" | "warning" | "success" | "info";
  onDismiss?: () => void;
  className?: string;
  scope?: RefObject<HTMLElement | null>;
}) {
  const [host, setHost] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    setHost(null);
    if (!message) return;
    let target = origin?.isConnected ? origin : null;
    const dialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')];
    const dialog = dialogs.filter(d => d.getClientRects().length).at(-1);
    if (dialog && (!target || !dialog.contains(target))) target = dialog.querySelector('button[type="submit"]') || dialog.lastElementChild as HTMLElement;
    if (scope?.current && (!target || !scope.current.contains(target))) {
      target = scope.current.querySelector<HTMLElement>('.camera-actions,.control-actions,.section-toolbar') || scope.current.querySelector('button');
    }
    if (!target || !target.getClientRects().length || target.closest(".ui-feedback")) return;
    const row = target.closest<HTMLElement>(".section-toolbar,.control-actions,.composer-actions,.camera-actions,.robot-draft-footer,.wizard-navigation") || target.closest<HTMLElement>("label") || target;
    if (!row.parentElement || row.closest("summary")) return;
    const slot = document.createElement("div"); slot.className = "feedback-host";
    row.after(slot); setHost(slot);
    slot.parentElement?.classList.add("has-action-feedback");
    return () => {
      const parent = slot.parentElement; slot.remove();
      if (!parent?.querySelector(":scope > .feedback-host")) parent?.classList.remove("has-action-feedback");
    };
  }, [message, scope]);
  useLayoutEffect(() => {
    if (host && message) host.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
  }, [host, message]);
  if (!message) return null;
  const Icon = kind === "error" || kind === "warning" ? AlertCircle : kind === "success" ? CheckCircle2 : Info;
  const capacity = message.includes("ZONE_RESOURCE_POOL_EXHAUSTED");
  const content = <div className={`ui-feedback ${className}`} data-kind={kind} role={kind === "error" || kind === "warning" ? "alert" : "status"} aria-atomic="true">
    <Icon size={18} aria-hidden="true" />
    <div className="feedback-text">{capacity ? "GPU capacity is unavailable in this zone. Retry later; your saved workspace is retained." : message}
      {capacity && <details><summary>Technical details</summary><pre>{message}</pre></details>}
    </div>
    {onDismiss && <button type="button" aria-label={kind === "error" ? "Dismiss error" : "Dismiss message"} onClick={onDismiss}><X size={16} /></button>}
  </div>;
  return host ? createPortal(content, host) : content;
}
