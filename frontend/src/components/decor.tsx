import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/cn";

/*
  MetrIQ decorative system.

  One coherent visual language layered on top of the Phase 7 design system
  (warm paper, charcoal structure, one cobalt accent, 1px borders). Every
  export here is presentational: aria-hidden, pointer-events-none, and safe to
  drop or scale away on small screens. Nothing here touches data, routing or
  behaviour.

  Vocabulary:
    BlueprintField  faint measurement grid behind large empty areas
    Bracket         technical corner brackets framing a surface
    Ticks           short measurement ticks along an edge
    SquareField     a composed scatter of cobalt squares + connector lines
    Annotation      a small mono diagram label, optionally with a lead line
    Figurine        the institutional figurine — a faceted Ashoka Lion Capital
    DigitHalftone   a field of mono digits forming a halftone gradient
*/

/* --------------------------------------------------------- BlueprintField --- */

export function BlueprintField({
  className,
  drift = false,
  fade = "radial",
  variant = "grid",
}: {
  className?: string;
  drift?: boolean;
  fade?: "radial" | "bottom" | "none";
  variant?: "grid" | "dots";
}) {
  const mask =
    fade === "radial"
      ? "radial-gradient(120% 120% at 72% 24%, #000 26%, transparent 82%)"
      : fade === "bottom"
        ? "linear-gradient(#000, transparent)"
        : undefined;
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className,
      )}
      aria-hidden
      style={mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined}
    >
      <div
        className={cn(
          variant === "dots" ? "dot-field" : "blueprint-field",
          "absolute inset-0",
          drift && "metriq-drift",
        )}
      />
    </div>
  );
}

/* --------------------------------------------------------------- Bracket --- */

/** Technical corner brackets. Pass a negative inset (e.g. "-inset-2") to
 *  frame around an element rather than on its edge. */
export function Bracket({
  className,
  tone = "accent",
  size = "md",
}: {
  className?: string;
  tone?: "accent" | "line";
  size?: "sm" | "md";
}) {
  const dim = size === "sm" ? "h-2 w-2" : "h-3 w-3";
  const color = tone === "accent" ? "border-accent/50" : "border-line-strong";
  const corner = cn("absolute", dim, color);
  return (
    <div
      className={cn("pointer-events-none absolute", className ?? "inset-0")}
      aria-hidden
    >
      <span className={cn(corner, "left-0 top-0 border-l border-t")} />
      <span className={cn(corner, "right-0 top-0 border-r border-t")} />
      <span className={cn(corner, "bottom-0 left-0 border-b border-l")} />
      <span className={cn(corner, "bottom-0 right-0 border-b border-r")} />
    </div>
  );
}

/* ----------------------------------------------------------------- Ticks --- */

/** A short run of measurement ticks along one edge. */
export function Ticks({
  edge = "top",
  count = 9,
  className,
}: {
  edge?: "top" | "bottom" | "left" | "right";
  count?: number;
  className?: string;
}) {
  const horizontal = edge === "top" || edge === "bottom";
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute flex",
        horizontal ? "left-0 right-0 justify-between" : "bottom-0 top-0 flex-col justify-between",
        edge === "top" && "top-0",
        edge === "bottom" && "bottom-0",
        edge === "left" && "left-0",
        edge === "right" && "right-0",
        className,
      )}
    >
      {Array.from({ length: count }).map((_, i) => (
        <span
          key={i}
          className={cn(
            "bg-line-strong",
            horizontal ? "w-px" : "h-px",
            horizontal ? (i % 3 === 0 ? "h-2" : "h-1") : i % 3 === 0 ? "w-2" : "w-1",
          )}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ SquareField --- */

type Sq = { x: number; y: number; s: number; v: "solid" | "mid" | "soft" | "outline" };

/**
 * A composed scatter of cobalt squares with faint connector lines — the
 * "evidence chips trailing toward the object" motif. Percent coordinates so it
 * scales with its container. Give the container `position: relative`.
 */
export function SquareField({
  squares,
  connect = true,
  className,
}: {
  squares: Sq[];
  connect?: boolean;
  className?: string;
}) {
  const fill: Record<Sq["v"], string> = {
    solid: "bg-accent/80",
    mid: "bg-accent/40",
    soft: "bg-accent/15",
    outline: "border border-accent/45",
  };
  return (
    <div
      aria-hidden
      className={cn("pointer-events-none absolute inset-0 overflow-visible", className)}
    >
      {connect && squares.length > 1 && (
        <svg
          className="absolute inset-0 h-full w-full"
          preserveAspectRatio="none"
          viewBox="0 0 100 100"
        >
          <polyline
            points={squares.map((q) => `${q.x},${q.y}`).join(" ")}
            fill="none"
            stroke="rgba(34,70,239,0.22)"
            strokeWidth="0.25"
            strokeDasharray="1 1.4"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      )}
      {squares.map((q, i) => (
        <span
          key={i}
          className={cn("absolute block", fill[q.v])}
          style={{
            left: `${q.x}%`,
            top: `${q.y}%`,
            width: q.s,
            height: q.s,
            transform: "translate(-50%,-50%)",
          }}
        />
      ))}
    </div>
  );
}

/** A single positioned square marker (for one-off accents). */
export function Square({
  className,
  variant = "solid",
  size = 8,
  style,
}: {
  className?: string;
  variant?: "solid" | "mid" | "soft" | "outline" | "tick";
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute block",
        variant === "solid" && "bg-accent/80",
        variant === "mid" && "bg-accent/40",
        variant === "soft" && "bg-accent/15",
        variant === "outline" && "border border-accent/45",
        variant === "tick" &&
          "border border-accent/45 after:absolute after:left-1/2 after:top-1/2 after:h-px after:w-1.5 after:-translate-x-1/2 after:-translate-y-1/2 after:bg-accent/55",
        className,
      )}
      style={{ width: size, height: size, ...style }}
    />
  );
}

/* -------------------------------------------------------------- Annotation --- */

/** A small mono diagram label. `lead` draws a short connector line. */
export function Annotation({
  children,
  lead,
  className,
}: {
  children: ReactNode;
  lead?: "left" | "right";
  className?: string;
}) {
  const line = <span className="h-px w-7 shrink-0 bg-accent/45" aria-hidden />;
  return (
    <span
      className={cn(
        "annotation inline-flex items-center gap-2 whitespace-nowrap",
        className,
      )}
    >
      {lead === "left" && line}
      {children}
      {lead === "right" && line}
    </span>
  );
}

/* ---------------------------------------------------------------- Figurine --- */

/**
 * The MetrIQ hero artwork — the cobalt-duotone Ashoka Lion Capital plate from
 * the project reference set (`public/hero-lion.png`), which already carries its
 * own blueprint dimension lines, corner brackets, blue markers and the
 * MEASURE → VERIFY / EVIDENCE FIRST / BIS · INDIA annotations. Placed as a
 * single composed block; position / crop / bleed via `className`.
 */
export function Figurine({
  className,
  blend = "normal",
}: {
  className?: string;
  blend?: "normal" | "multiply" | "luminosity";
}) {
  return (
    <img
      src="/hero-lion.png"
      alt=""
      aria-hidden
      draggable={false}
      className={cn("pointer-events-none select-none", className)}
      style={blend === "normal" ? undefined : { mixBlendMode: blend }}
    />
  );
}

/* Back-compat alias. */
export const LionCapitalMark = Figurine;

/* ------------------------------------------------------------------- Motif --- */

/**
 * A blue-duotone illustration fragment from the reference plate set (lotus,
 * chhatri dome, carved pillar, fingerprint, mountains, botanical). Feathered
 * edges, so it dissolves into the paper. Used as editorial section artwork —
 * one per surface, cropped and bled, never inside a card.
 */
type MotifName =
  | "lotus"
  | "dome"
  | "pillar"
  | "fingerprint"
  | "mountain"
  | "botanical";

export function Motif({
  name,
  className,
  style,
}: {
  name: MotifName;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <img
      src={`/motif-${name}.png`}
      alt=""
      aria-hidden
      draggable={false}
      className={cn("pointer-events-none select-none object-contain", className)}
      style={style}
    />
  );
}

/**
 * A section-header artwork block: a blue-duotone motif bleeding off the right
 * edge in the header's whitespace, over a faint grid, with a small mono label
 * and a corner bracket. Drop it as the first child of a `relative` wrapper
 * around a <PageHeader>. Hidden below md so it never crowds small screens.
 */
export function HeaderMotif({
  name,
  label,
  width = "w-[26%]",
}: {
  name: MotifName;
  label: string;
  width?: string;
}) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute -top-6 right-0 hidden h-[150%] overflow-hidden md:block",
        width,
      )}
      aria-hidden
    >
      <BlueprintField fade="bottom" />
      <Motif
        name={name}
        className="absolute -right-4 top-0 h-[86%] w-auto max-w-none opacity-90"
      />
      <Bracket tone="line" className="inset-4" />
      <span className="annotation absolute bottom-3 left-3">{label}</span>
    </div>
  );
}

/* ------------------------------------------------------------ PhotoFragment --- */

/**
 * A cropped fragment of one of the project's blue photographic assets, used as
 * visual punctuation — a narrow strip, an edge bleed, a background sliver. Not
 * a card image. `blend` integrates it with whatever it sits on.
 */
export function PhotoFragment({
  src,
  className,
  blend = "normal",
  opacity,
  style,
}: {
  src: string;
  className?: string;
  blend?: "normal" | "multiply" | "screen" | "luminosity" | "soft-light";
  opacity?: number;
  style?: CSSProperties;
}) {
  return (
    <img
      src={src}
      alt=""
      aria-hidden
      draggable={false}
      className={cn(
        "pointer-events-none select-none object-cover",
        className,
      )}
      style={{
        mixBlendMode: blend === "normal" ? undefined : blend,
        opacity,
        ...style,
      }}
    />
  );
}

/* ------------------------------------------------------------- DigitHalftone --- */

const DIGIT_ROWS = 14;
const DIGIT_COLS = 60;

/**
 * A field of monospace digits whose density/brightness rises left→right,
 * forming a halftone gradient. Sits inside the (already blue) system-layer
 * footer. Decorative; the digits carry no meaning.
 */
export function DigitHalftone({ className }: { className?: string }) {
  const rows: string[] = [];
  for (let r = 0; r < DIGIT_ROWS; r++) {
    let line = "";
    for (let c = 0; c < DIGIT_COLS; c++) {
      const t = c / DIGIT_COLS;
      const jitter = ((r * 7 + c * 13) % 11) / 11;
      line += t + jitter * 0.5 > 0.7 ? String((r * 3 + c * 7) % 10) : " ";
    }
    rows.push(line);
  }
  return (
    <pre
      aria-hidden
      className={cn(
        "pointer-events-none absolute bottom-0 right-0 select-none overflow-hidden font-mono text-[9px] leading-[11px] text-white/25",
        className,
      )}
    >
      {rows.join("\n")}
    </pre>
  );
}

/* -------------------------------------------------------------- BrailleField --- */

/**
 * A field of real Unicode braille cells (U+2800..U+28FF) whose dot-density
 * falls off toward one edge, forming a soft halftone.
 *
 * MetrIQ's own answer to the reference plate's numeral texture. Braille is the
 * right motif here because the whole product is about reading marks off a
 * physical surface — but it is DECORATION and nothing more: the cells are
 * generated from a hash, they spell nothing, and this element provides NO
 * accessibility function. Always `aria-hidden`, never over readable text.
 */
export function BrailleField({
  className,
  rows = 12,
  cols = 48,
  tone = "ink",
}: {
  className?: string;
  rows?: number;
  cols?: number;
  tone?: "ink" | "white";
}) {
  const lines: string[] = [];
  for (let r = 0; r < rows; r++) {
    let line = "";
    for (let c = 0; c < cols; c++) {
      // Density rises to the left, so the field dissolves as it travels right.
      const t = 1 - c / cols;
      const jitter = ((r * 17 + c * 31) % 13) / 13;
      if (t * 0.8 + jitter * 0.45 > 0.62) {
        // Pick a cell with 1-5 raised dots; the low bits give lighter glyphs.
        const bits = ((r * 5 + c * 11) % 63) | 1;
        line += String.fromCharCode(0x2800 + bits);
      } else {
        line += "⠀"; // blank braille cell — keeps the grid rigid
      }
    }
    lines.push(line);
  }
  return (
    <pre
      aria-hidden
      className={cn(
        "braille pointer-events-none absolute select-none overflow-hidden text-[11px]",
        tone === "white" ? "text-white/20" : "text-accent/15",
        className,
      )}
    >
      {lines.join("\n")}
    </pre>
  );
}
