import { useState } from "react";
import { Mono } from "@/components/ui";
import type { OcrRegion } from "@/lib/api";

/**
 * The uploaded package image with the real OCR regions overlaid. Selecting a
 * region here highlights it in the detected-text panel and vice-versa.
 *
 * OCR bounding boxes come back in source-image pixels; we convert them to
 * percentages of the natural image size so the overlay tracks any rendered
 * width.
 */
export function ImageInspector({
  src,
  label = "Package image 01",
  width,
  height,
  regions,
  selectedId,
  linkedIds = [],
  onSelect,
}: {
  src: string;
  label?: string;
  width: number;
  height: number;
  regions: OcrRegion[];
  selectedId: string | null;
  /** Extra regions to highlight, e.g. every source box of a declaration. */
  linkedIds?: string[];
  onSelect: (id: string | null) => void;
}) {
  const [hoverId, setHoverId] = useState<string | null>(null);
  const activeId = hoverId ?? selectedId;
  const safeW = width || 1;
  const safeH = height || 1;

  return (
    <div className="border border-line bg-raised">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <Mono muted className="text-[11px] uppercase tracking-[0.12em]">
          {label}
        </Mono>
        <Mono muted className="text-[11px]">
          {regions.length} {regions.length === 1 ? "region" : "regions"}
        </Mono>
      </div>

      <div className="relative overflow-hidden bg-[#efeee9]">
        <img
          src={src}
          alt="Inspected package"
          className="block w-full select-none"
          draggable={false}
        />
        <svg
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden
        >
          {regions.map((r) => {
            const [x1, y1, x2, y2] = r.bbox;
            const x = (x1 / safeW) * 100;
            const y = (y1 / safeH) * 100;
            const w = ((x2 - x1) / safeW) * 100;
            const h = ((y2 - y1) / safeH) * 100;
            const active =
              r.id === activeId || (hoverId === null && linkedIds.includes(r.id));
            return (
              <rect
                key={r.id}
                x={x}
                y={y}
                width={w}
                height={h}
                vectorEffect="non-scaling-stroke"
                className="cursor-pointer transition-[fill-opacity,stroke] duration-150"
                fill="var(--color-accent)"
                fillOpacity={active ? 0.12 : 0}
                stroke={active ? "var(--color-accent)" : "rgba(23,24,27,0.4)"}
                strokeWidth={active ? 2 : 1}
                onMouseEnter={() => setHoverId(r.id)}
                onMouseLeave={() => setHoverId(null)}
                onClick={() => onSelect(r.id === selectedId ? null : r.id)}
              />
            );
          })}
        </svg>

        {/* text tag for the hovered / selected region */}
        {regions
          .filter((r) => r.id === activeId)
          .map((r) => (
            <div
              key={r.id}
              className="pointer-events-none absolute max-w-[70%] -translate-y-full truncate border border-accent bg-accent px-1.5 py-0.5 font-mono text-[10px] text-white"
              style={{
                left: `${(r.bbox[0] / safeW) * 100}%`,
                top: `${(r.bbox[1] / safeH) * 100}%`,
              }}
            >
              {r.text}
            </div>
          ))}
      </div>

      <div className="border-t border-line px-4 py-2.5">
        <Mono muted className="text-[10px] uppercase tracking-[0.12em]">
          Bounding boxes are the OCR engine's estimates
        </Mono>
      </div>
    </div>
  );
}
