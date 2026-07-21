// Line-vector module glyphs for the launcher cards — bright gradient
// stroke-art on the neomorphic tile (.mod-icon-tile in index.css).
// Inline SVG so they theme, scale and ship with zero asset requests.

import type { JSX } from "react";

function Machining({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="mg-mach" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#5fb0ff" />
          <stop offset="1" stopColor="#2f6fe0" />
        </linearGradient>
      </defs>
      <g stroke="url(#mg-mach)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        {/* workpiece with the milled pocket */}
        <path d="M7 40 h34 M9 40 v-8 h9 v-4 h12 v4 h9 v8" />
        {/* spindle + end mill */}
        <path d="M24 6 v7" />
        <path d="M20 13 h8 v5 l-1.6 7 h-4.8 L20 18 z" />
        {/* flutes */}
        <path d="M22 20 l4.4 2.6 M21.6 23.4 l4.4 2.6" opacity="0.8" />
        {/* chips flying off the cut */}
        <path d="M14 26 l-3 -2.6 M12.5 30 l-3.6 -1" opacity="0.7" />
        <path d="M34 26 l3 -2.6 M35.5 30 l3.6 -1" opacity="0.7" />
      </g>
    </svg>
  );
}

function Welding({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="mg-weld" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#ffb156" />
          <stop offset="1" stopColor="#ff5f3c" />
        </linearGradient>
      </defs>
      <g stroke="url(#mg-weld)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        {/* torch body + nozzle, angled in from top-right */}
        <path d="M40 8 l-7 7 M35.5 9.5 l3 3" />
        <path d="M33 15 l-4.5 4.5 a3.2 3.2 0 0 1 -4.5 -4.5 L28.5 10.5 a3.2 3.2 0 0 1 4.5 4.5 z" />
        {/* arc burst at the weld point */}
        <path d="M22 26 l-3.5 -3.5 M20 30 l-4.5 -1.4 M26 24 l1.4 -4.5" opacity="0.85" />
        {/* weld bead on the seam */}
        <path d="M8 36 q3 -3 6 0 t6 0 t6 0 t6 0" />
        <path d="M8 41 h32" opacity="0.55" />
      </g>
    </svg>
  );
}

function SheetLaser({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="mg-laser" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#a97dff" />
          <stop offset="1" stopColor="#5f8bff" />
        </linearGradient>
      </defs>
      <g stroke="url(#mg-laser)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        {/* laser head */}
        <path d="M20 6 h8 l-2 6 h-4 z" />
        {/* beam — dashed */}
        <path d="M24 13 v13" strokeDasharray="3.5 3" />
        {/* spark star at the cut point */}
        <path d="M24 28 l0 .01 M19.5 25 l-3 -2 M28.5 25 l3 -2 M20.5 31 l-3.4 1.4 M27.5 31 l3.4 1.4" opacity="0.85" />
        {/* bent sheet (press-brake L profile in perspective) */}
        <path d="M6 34 l14 -6 h18 l-8 6 z" />
        <path d="M12 40 l-6 -6 M30 40 l-8 -6 M38 34 l-8 6 h-18" opacity="0.75" />
        {/* kerf already cut */}
        <path d="M24 28 l6 2.6" strokeDasharray="2.5 2.5" opacity="0.8" />
      </g>
    </svg>
  );
}

function Printing({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="mg-print" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#2fd4b2" />
          <stop offset="1" stopColor="#19a9d6" />
        </linearGradient>
      </defs>
      <g stroke="url(#mg-print)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        {/* gantry + carriage */}
        <path d="M7 9 h34 M15 9 v4 M33 9 v4" opacity="0.75" />
        <path d="M20 13 h8 v4 l-4 4 l-4 -4 z" />
        {/* filament drop */}
        <path d="M24 22 v4" strokeDasharray="2.5 2.5" opacity="0.8" />
        {/* layered part building up */}
        <path d="M15 40 h18" />
        <path d="M16.5 35.5 h15" />
        <path d="M18 31 h9" />
        <path d="M18 31 a9 9 0 0 1 9 0" opacity="0.75" />
      </g>
    </svg>
  );
}

const GLYPHS: Record<string, ({ size }: { size: number }) => JSX.Element> = {
  machining: Machining,
  fabrication: Welding,
  sheetmetal: SheetLaser,
  printing: Printing,
};

export function ModuleGlyph({ k, size = 30 }: { k: string; size?: number }) {
  const G = GLYPHS[k];
  return G ? <G size={size} /> : null;
}
