import { useRef, useState } from "react";
import { Minus, Plus, Maximize } from "lucide-react";
import type { Asset } from "./types";
export default function FloorPlan({
  assets,
  selected,
  onSelect,
}: {
  assets: Asset[];
  selected: string;
  onSelect: (asset: Asset) => void;
}) {
  const items = assets
    .filter((a) => a.kind !== "floor")
    .sort((a, b) => Number(a.kind === "object") - Number(b.kind === "object"));
  const moved = useRef(false);
  const minX = Math.min(-0.3, ...items.map((a) => a.position.x - a.size.x / 2)),
    maxX = Math.max(0.7, ...items.map((a) => a.position.x + a.size.x / 2));
  const minY = Math.min(-0.4, ...items.map((a) => a.position.y - a.size.y / 2)),
    maxY = Math.max(0.5, ...items.map((a) => a.position.y + a.size.y / 2));
  const [zoom, setZoom] = useState(1),
    [pan, setPan] = useState({ x: 0, y: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const start = useRef<{
    x: number;
    y: number;
    pan: { x: number; y: number };
    distance: number;
    zoom: number;
  } | null>(null);
  const width = (maxX - minX + 0.3) / zoom,
    height = (maxY - minY + 0.3) / zoom,
    box = `${(minX + maxX - width) / 2 + pan.x} ${-(minY + maxY + height) / 2 + pan.y} ${width} ${height}`;
  return (
    <div className="floor-plan">
      <svg
        aria-label="Touch-friendly workspace floor plan"
        viewBox={box}
        onPointerDown={(e) => {
          moved.current = false;
          pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
          const pts = [...pointers.current.values()];
          start.current = {
            x: e.clientX,
            y: e.clientY,
            pan: { ...pan },
            distance:
              pts.length === 2
                ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)
                : 0,
            zoom,
          };
        }}
        onPointerMove={(e) => {
          if (!pointers.current.has(e.pointerId) || !start.current) return;
          if (
            Math.hypot(
              e.clientX - start.current.x,
              e.clientY - start.current.y,
            ) > 8
          ) {
            moved.current = true;
            e.currentTarget.setPointerCapture(e.pointerId);
          }
          pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
          const pts = [...pointers.current.values()];
          if (pts.length === 2 && start.current.distance) {
            const d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
            setZoom(
              Math.min(
                8,
                Math.max(
                  0.5,
                  (start.current.zoom * d) / start.current.distance,
                ),
              ),
            );
          } else if (pts.length === 1) {
            const r = e.currentTarget.getBoundingClientRect();
            setPan({
              x:
                start.current.pan.x -
                ((e.clientX - start.current.x) * width) / r.width,
              y:
                start.current.pan.y -
                ((e.clientY - start.current.y) * height) / r.height,
            });
          }
        }}
        onPointerUp={(e) => {
          pointers.current.delete(e.pointerId);
          start.current = null;
        }}
        onPointerCancel={(e) => {
          pointers.current.delete(e.pointerId);
          start.current = null;
        }}
      >
        <defs>
          <pattern
            id="grid"
            width=".1"
            height=".1"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M .1 0 L 0 0 0 .1"
              fill="none"
              stroke="#2d394c"
              strokeWidth=".0015"
            />
          </pattern>
        </defs>
        <rect x={-100} y={-100} width={200} height={200} fill="url(#grid)" />
        {items.map((a) => (
          <g
            key={a.id}
            role="button"
            tabIndex={0}
            aria-label={`Map asset ${a.name}`}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(a);
              }
            }}
            onClick={() => {
              if (moved.current) return;
              onSelect(a);
            }}
            className={selected === a.id ? "selected" : ""}
          >
            <rect
              x={a.position.x - a.size.x / 2}
              y={-a.position.y - a.size.y / 2}
              width={Math.max(0.04, a.size.x)}
              height={Math.max(0.04, a.size.y)}
              rx=".012"
              fill={
                a.kind === "object"
                  ? "#f4bd78"
                  : a.kind === "region"
                    ? "#a6d4c6"
                    : "#c3cfda"
              }
              stroke={selected === a.id ? "#90baff" : "#8094af"}
              strokeWidth=".003"
            />
            <text
              x={a.position.x}
              y={
                -a.position.y +
                (a.kind === "object"
                  ? -a.size.y / 2 - 0.03
                  : a.size.y / 2 + 0.03)
              }
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={Math.max(0.025, width / 45)}
              fill="var(--ui-text)"
              stroke="var(--ui-surface)"
              strokeWidth=".007"
              paintOrder="stroke"
              strokeLinejoin="round"
            >
              {a.name}
            </text>
          </g>
        ))}
      </svg>
      <div className="map-controls">
        <button
          aria-label="Zoom in"
          onClick={() => setZoom(Math.min(8, zoom * 1.3))}
        >
          <Plus size={18} />
        </button>
        <button
          aria-label="Zoom out"
          onClick={() => setZoom(Math.max(0.5, zoom / 1.3))}
        >
          <Minus size={18} />
        </button>
        <button
          aria-label="Fit floor plan"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          <Maximize size={18} />
        </button>
      </div>
      <span className="map-hint">Drag to explore · pinch to zoom</span>
    </div>
  );
}
