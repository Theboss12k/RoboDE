import Feedback from "../../SERVER_CLIENT/client/src/ui/Feedback";
import { useEffect, useState } from "react";
import { api, post } from "./api";
type GPU = {
  configured: boolean;
  status: string;
  message: string;
  idle_minutes?: number;
  max_session_minutes?: number;
};
export default function GpuStart({
  onReady,
}: {
  onReady: () => Promise<void>;
}) {
  const [gpu, setGpu] = useState<GPU | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    void api<GPU>("/gpu")
      .then(setGpu)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (gpu?.status !== "starting") return;
    const timer = setInterval(
      () =>
        void api<GPU>("/gpu")
          .then(async (next) => {
            setGpu(next);
            if (next.status === "ready") await onReady();
          })
          .catch((e) => setError(e.message)),
      3000,
    );
    return () => clearInterval(timer);
  }, [gpu?.status]);
  if (!gpu?.configured) return <Feedback message={error} />;
  return (
    <div className="gpu-start">
      <Feedback message={gpu.status === "error" ? gpu.message : ""} />
      <p>
        {gpu.status !== "error" && gpu.message}{" "}
        {gpu.idle_minutes
          ? `Idle shutdown: ${gpu.idle_minutes} min. Session limit: ${gpu.max_session_minutes} min.`
          : ""}
      </p>
      <button
        className="secondary"
        disabled={gpu.status === "starting"}
        onClick={() => {
          setError("");
          void post<GPU>("/gpu/start")
            .then(setGpu)
            .catch((e) => setError(e.message));
        }}
      >
        {gpu.status === "starting"
          ? "Starting GPU…"
          : gpu.status === "ready"
            ? "Connect GPU workspace"
            : "Start GPU processing"}
      </button>
      <Feedback message={error} />
    </div>
  );
}
