import { useState } from "react";
import { api, post } from "./api";
import Feedback from "./ui/Feedback";
export default function RoomCaptureImport({
  projectId,
}: {
  projectId: string;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  return (
    <section className="config-card">
      <h3>Room capture import</h3>
      <p>
        For offline desktops, transfer the Business App’s exported photo ZIP or
        a reconstructed USDZ to this computer, then upload it here. Photos need
        reconstruction before they can become simulator geometry.
      </p>
      <label className="field">
        Import capture ZIP / room USDZ
        <input
          aria-label="Import mobile room capture"
          type="file"
          accept=".zip,.usdz"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            void (async () => {
              setBusy(true);
              setError("");
              setMessage("");
              try {
                if (f.name.toLowerCase().endsWith(".zip")) {
                  const result = await api<{ name: string; photos: number }>(
                    `/business/projects/${projectId}/rooms/import-capture`,
                    {
                      method: "POST",
                      body: f,
                      headers: { "Content-Type": "application/zip" },
                    },
                  );
                  setMessage(
                    `Imported ${result.name}: ${result.photos} photos. Saved on this IDE; reconstruction is still required.`,
                  );
                } else {
                  const r = await post<{ id: string }>(
                    `/business/projects/${projectId}/rooms`,
                    { name: f.name.replace(/\.usdz$/i, "") },
                  );
                  await api(
                    `/business/projects/${projectId}/rooms/${r.id}/scene`,
                    {
                      method: "PUT",
                      body: f,
                      headers: { "Content-Type": "model/vnd.usdz+zip" },
                    },
                  );
                  setMessage(
                    "Room scene imported. Review metric scale, alignment and named collision assets in the room manager before deploying to Isaac Sim.",
                  );
                }
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            })();
          }}
        />
      </label>
      <Feedback message={error} />
      <Feedback message={message} kind="success" />
      <small>
        Capture files remain on this installation. Importing does not move
        robots or change the active environment. Open the local Business App’s
        Room capture manager to reconstruct, align and explicitly deploy the
        saved capture.
      </small>
    </section>
  );
}
