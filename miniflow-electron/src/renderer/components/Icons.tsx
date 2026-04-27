// Stroke icon set — 1.6px strokes, 20×20 viewbox, currentColor.
// Replaces emoji usage (🔥 🚀 🏆 ⚡ 🎙) throughout the UI.
// Ported from the design package's icons.jsx.

import React from "react";

interface IconProps {
  size?: number;
  stroke?: number;
  fill?: string;
  style?: React.CSSProperties;
  className?: string;
}

function Icon({
  d, size = 18, stroke = 1.6, fill = "none", style, className,
}: IconProps & { d: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill={fill}
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      className={className}
    >
      {typeof d === "string" ? <path d={d}/> : d}
    </svg>
  );
}

export const IconHome = (p: IconProps) => (
  <Icon {...p} d={<>
    <path d="M3 9 L10 3 L17 9 V16 a1 1 0 0 1 -1 1 H4 a1 1 0 0 1 -1 -1 Z"/>
    <path d="M8 17 V12 h4 v5"/>
  </>}/>
);

export const IconBook = (p: IconProps) => (
  <Icon {...p} d={<>
    <path d="M4 3 h8 a3 3 0 0 1 3 3 V17 H7 a3 3 0 0 1 -3 -3 Z"/>
    <path d="M4 14 a3 3 0 0 1 3 -3 h8"/>
  </>}/>
);

export const IconSnip = (p: IconProps) => (
  <Icon {...p} d={<>
    <circle cx="6" cy="6" r="2.5"/>
    <circle cx="6" cy="14" r="2.5"/>
    <path d="M8 7 L17 13"/>
    <path d="M8 13 L17 7"/>
  </>}/>
);

export const IconGear = (p: IconProps) => (
  <Icon {...p} d={<>
    <circle cx="10" cy="10" r="3"/>
    <path d="M10 2 v2 M10 16 v2 M2 10 h2 M16 10 h2 M4.2 4.2 l1.4 1.4 M14.4 14.4 l1.4 1.4 M4.2 15.8 l1.4 -1.4 M14.4 5.6 l1.4 -1.4"/>
  </>}/>
);

export const IconHelp = (p: IconProps) => (
  <Icon {...p} d={<>
    <circle cx="10" cy="10" r="7"/>
    <path d="M7.5 8 a2.5 2.5 0 1 1 3.5 2.3 c -1 0.5 -1 1.2 -1 2"/>
    <circle cx="10" cy="14.5" r="0.5" fill="currentColor"/>
  </>}/>
);

export const IconMic = (p: IconProps) => (
  <Icon {...p} d={<>
    <rect x="7" y="2" width="6" height="11" rx="3"/>
    <path d="M4 10 a6 6 0 0 0 12 0"/>
    <path d="M10 16 v2"/>
  </>}/>
);

export const IconRocket = (p: IconProps) => (
  <Icon {...p} d={<>
    <path d="M14 3 a9 9 0 0 0 -9 9 l 1 1 l 4 -1 l 3 3 l -1 4 l 1 1 a 9 9 0 0 0 9 -9 Z" transform="translate(-1 -1)"/>
    <circle cx="12" cy="8" r="1.3"/>
  </>}/>
);

export const IconTrophy = (p: IconProps) => (
  <Icon {...p} d={<>
    <path d="M6 3 h8 v5 a4 4 0 0 1 -8 0 Z"/>
    <path d="M6 5 H3 v2 a3 3 0 0 0 3 3"/>
    <path d="M14 5 h3 v2 a3 3 0 0 0 -3 3"/>
    <path d="M10 12 v3"/>
    <path d="M7 17 h6"/>
  </>}/>
);

export const IconSearch = (p: IconProps) => (
  <Icon {...p} d={<>
    <circle cx="9" cy="9" r="5"/>
    <path d="M13 13 l4 4"/>
  </>}/>
);

export const IconCheck = (p: IconProps) => <Icon {...p} d="M4 10 l4 4 l8 -8"/>;

export const IconX = (p: IconProps) => <Icon {...p} d="M5 5 l10 10 M15 5 l-10 10"/>;

export const IconSpark = (p: IconProps) => (
  <Icon {...p} d={<><path d="M10 3 L11 8 L16 10 L11 12 L10 17 L9 12 L4 10 L9 8 Z"/></>}/>
);

export const IconArrow = (p: IconProps) => <Icon {...p} d="M4 10 h12 M12 6 l4 4 l-4 4"/>;

export const IconPlus = (p: IconProps) => <Icon {...p} d="M10 4 v12 M4 10 h12"/>;

export const IconBolt = (p: IconProps) => <Icon {...p} d="M11 2 L4 11 h5 L8 18 L15 9 h-5 Z"/>;

export const IconChevron = (p: IconProps) => <Icon {...p} d="M7 5 l5 5 l-5 5"/>;

export const IconWave = (p: IconProps) => (
  <Icon {...p} d="M2 10 Q 4 6 6 10 Q 8 14 10 10 Q 12 6 14 10 Q 16 14 18 10"/>
);

export const IconPlay = (p: IconProps) => <Icon {...p} d="M6 4 L 16 10 L 6 16 Z" fill="currentColor"/>;
