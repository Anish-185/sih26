import { createContext, useContext } from "react";
import { cn } from "@/lib/cn";
import { Mono } from "@/components/ui";
import type { OcrRegion, PackageCoverage, PackageImage } from "@/lib/api";
import { ImageInspector } from "./ImageInspector";

/** Region id -> the side of the photo it was read from, for evidence labels. */
export const RegionSides = createContext<Map<string, string>>(new Map());

/** "BACK · I2-OCR-004 + BACK · I2-OCR-005" — side shown only when the officer set one. */
export function useWhere() {
  const sides = useContext(RegionSides);
  return (ids: string[]) =>
    ids
      .map((id) => {
        const side = sides.get(id);
        return side && side !== "UNKNOWN" ? `${side} · ${id}` : id;
      })
      .join(" + ");
}

export function regionSides(images: PackageImage[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const img of images) for (const r of img.ocr?.regions ?? []) map.set(r.id, img.side);
  return map;
}

const STATUS_LABEL: Record<PackageImage["status"], string> = {
  COMPLETED: "OCR complete",
  NO_RELIABLE_TEXT: "No reliable text",
  NO_TEXT: "No text detected",
  FAILED: "OCR failed",
};

function sideName(img: PackageImage) {
  return img.side === "UNKNOWN" ? `Image ${img.index}` : img.side;
}

/**
 * Every photo of the package as a card, plus the active photo with its OCR
 * boxes. Selecting evidence elsewhere switches to the photo it came from.
 */
export function PackageImages({
  images,
  urls,
  coverage,
  activeImageId,
  onActivate,
  selectedId,
  linkedIds,
  onSelect,
}: {
  images: PackageImage[];
  urls: string[]; // object URL per upload, in upload order
  coverage: PackageCoverage;
  activeImageId: string;
  onActivate: (imageId: string) => void;
  selectedId: string | null;
  linkedIds: string[];
  onSelect: (id: string | null) => void;
}) {
  const active = images.find((i) => i.image_id === activeImageId) ?? images[0];
  const url = urls[active.index - 1];
  const multi = images.length > 1;

  return (
    <div className="space-y-3">
      {multi && (
        <div className="border border-line bg-raised">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <Mono muted className="text-[11px] uppercase tracking-[0.12em]">
              Package images
            </Mono>
            <Mono muted className="text-[11px]">
              {coverage.usable_images} of {coverage.image_count} readable
            </Mono>
          </div>
          <ul className="grid grid-cols-3 gap-px bg-line">
            {images.map((img) => {
              const isActive = img.image_id === active.image_id;
              const hasSelected = (img.ocr?.regions ?? []).some((r: OcrRegion) => linkedIds.includes(r.id));
              return (
                <li key={img.image_id}>
                  <button
                    type="button"
                    onClick={() => onActivate(img.image_id)}
                    className={cn(
                      "relative block h-full w-full bg-raised p-2 text-left transition-colors",
                      isActive ? "bg-accent-soft" : "hover:bg-surface",
                    )}
                  >
                    <img
                      src={urls[img.index - 1]}
                      alt={`${sideName(img)} photo`}
                      className={cn("block h-16 w-full object-cover", img.status === "FAILED" && "opacity-40")}
                    />
                    <div className="mt-1.5 flex items-center justify-between gap-1">
                      <Mono className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink">
                        {sideName(img)}
                      </Mono>
                      {hasSelected && <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-label="has selected evidence" />}
                    </div>
                    <Mono
                      className={cn(
                        "block text-[10px]",
                        img.status === "COMPLETED" ? "text-ink-faint" : img.status === "FAILED" ? "text-fail" : "text-review",
                      )}
                    >
                      {img.status === "COMPLETED" ? `${img.ocr?.region_count ?? 0} regions` : STATUS_LABEL[img.status]}
                    </Mono>
                  </button>
                </li>
              );
            })}
          </ul>
          {coverage.sides_not_uploaded.length > 0 && (
            <p className="border-t border-line px-4 py-2 text-[11px] text-ink-faint">
              Not photographed: {coverage.sides_not_uploaded.join(" · ")} — nothing from these sides was checked.
            </p>
          )}
        </div>
      )}

      {active.ocr ? (
        <ImageInspector
          src={url}
          label={`${multi ? `${sideName(active)} · ` : "Package image · "}${active.width}×${active.height}`}
          width={active.width ?? 1}
          height={active.height ?? 1}
          regions={active.ocr.regions}
          selectedId={selectedId}
          linkedIds={linkedIds}
          onSelect={onSelect}
        />
      ) : (
        <div className="border border-line bg-raised">
          <div className="border-b border-line px-4 py-2.5">
            <Mono muted className="text-[11px] uppercase tracking-[0.12em]">
              {sideName(active)} · OCR failed
            </Mono>
          </div>
          <img src={url} alt={`${sideName(active)} photo`} className="block w-full opacity-50" />
          <p className="px-4 py-3 text-[12px] leading-relaxed text-fail">
            {active.error} No evidence was read from this photo. That does not mean
            anything is absent from the package.
          </p>
        </div>
      )}
    </div>
  );
}
