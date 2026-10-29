import Feedback from "../../SERVER_CLIENT/client/src/ui/Feedback";
import { useEffect, useRef, useState } from "react";
import { Camera, Check, X } from "lucide-react";

/** Phone camera produces ordinary overlapping photos, not metric geometry. */
export default function RoomCamera({
  onPhoto,
  onClose,
}: {
  onPhoto: (photo: Blob) => Promise<void>;
  onClose: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  const video = useRef<HTMLVideoElement>(null),
    stream = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false),
    [saving, setSaving] = useState(false),
    [error, setError] = useState(""),
    [count, setCount] = useState(0);
  useEffect(() => {
    let disposed = false;
    async function open() {
      try {
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
          throw new Error(
            "The camera requires HTTPS. Open the secure workspace link on your phone, or add photos from your camera roll.",
          );
        const media = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (disposed) {
          media.getTracks().forEach((t) => t.stop());
          return;
        }
        stream.current = media;
        if (video.current) {
          video.current.srcObject = media;
          await video.current.play();
        }
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    }
    void open();
    return () => {
      disposed = true;
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = null;
    };
  }, []);
  async function capture() {
    if (!video.current || saving) return;
    setSaving(true);
    setError("");
    try {
      const canvas = document.createElement("canvas"),
        v = video.current;
      canvas.width = v.videoWidth;
      canvas.height = v.videoHeight;
      if (!canvas.width || !canvas.height)
        throw new Error("Wait for the camera to be ready.");
      canvas.getContext("2d")!.drawImage(v, 0, 0);
      const photo = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob(
          (b) => (b ? resolve(b) : reject(new Error("Photo capture failed."))),
          "image/jpeg",
          0.92,
        ),
      );
      await onPhoto(photo);
      setCount((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section ref={panel} className="room-camera" aria-label="Room camera">
      <div className="camera-heading">
        <h3>Walk, pause, capture.</h3>
        <button
          aria-label="Close room camera"
          onClick={onClose}
          disabled={saving}
        >
          <X size={20} />
        </button>
      </div>
      <video
        ref={video}
        autoPlay
        playsInline
        muted
        onLoadedData={() => setReady(true)}
      />
      <p>
        Move slowly around the room. Pause for each photo and keep about
        two-thirds of the previous view in frame. Capture corners and different
        heights.
      </p>
      <div className="camera-actions">
        <span role="status">
          <Check size={17} /> {count} photos saved this session
        </span>
        <button
          className="primary"
          disabled={!ready || saving}
          onClick={() => void capture()}
        >
          <Camera size={20} />
          {saving ? "Saving photo…" : "Take photo"}
        </button>
      </div>
      <Feedback message={error} scope={panel} />
    </section>
  );
}
