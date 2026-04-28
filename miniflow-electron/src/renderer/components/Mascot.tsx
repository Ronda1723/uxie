// Uxie mascot — bean body, three-peak soundwave tuft, sparkle eyes, blush cheeks.
// Ported from the design package's mascot.jsx (Uxie design pass 1).
// Moods drive eye / mouth / accent details; size is a single dimension (svg is square).

import React, { useId } from "react";

export type MascotMood = "idle" | "listening" | "sleeping" | "excited" | "thinking";

interface MascotProps {
  size?: number;
  mood?: MascotMood;
  accent?: string;
}

const MOUTH: Record<MascotMood, string> = {
  idle:      "M 57 76 Q 64 82 71 76 Q 64 79 57 76 Z",
  listening: "M 55 75 Q 64 86 73 75 Q 64 80 55 75 Z",
  sleeping:  "M 59 78 Q 64 80 69 78",
  excited:   "M 52 74 Q 64 90 76 74 Q 64 82 52 74 Z",
  thinking:  "M 58 78 Q 64 76 70 78",
};

export function UxieMascot({ size = 120, mood = "idle", accent = "var(--accent, #d97757)" }: MascotProps) {
  const skin       = "#faecc8";
  const skinMid    = "#f0d9a4";
  const skinShadow = "#ddbe80";
  const cheek      = "#f29a92";
  const ink        = "#2a1f15";
  const uid = useId().replace(/:/g, "-");

  const mouth   = MOUTH[mood] ?? MOUTH.idle;
  const eyeR    = mood === "sleeping" ? 0.15 : 1;
  const filled  = mood === "excited" || mood === "listening";

  return (
    <svg width={size} height={size} viewBox="0 0 128 128" style={{ overflow: "visible" }}>
      <defs>
        <radialGradient id={`body-${uid}`} cx="48%" cy="36%" r="75%">
          <stop offset="0%"   stopColor={skin}/>
          <stop offset="58%"  stopColor={skinMid}/>
          <stop offset="100%" stopColor={skinShadow}/>
        </radialGradient>
        <radialGradient id={`glow-${uid}`} cx="35%" cy="30%" r="32%">
          <stop offset="0%"   stopColor="rgba(255,255,255,0.75)"/>
          <stop offset="100%" stopColor="rgba(255,255,255,0)"/>
        </radialGradient>
        <radialGradient id={`cheek-${uid}`} cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor={cheek} stopOpacity="0.85"/>
          <stop offset="100%" stopColor={cheek} stopOpacity="0"/>
        </radialGradient>
        <filter id={`soft-${uid}`}>
          <feDropShadow dx="0" dy="3" stdDeviation="2.4" floodOpacity="0.16"/>
        </filter>
      </defs>

      {/* ground shadow */}
      <ellipse cx="64" cy="120" rx="32" ry="3.5" fill="rgba(30,20,10,0.14)" />

      {/* tuft — three filled peaks, wagging while listening */}
      <g style={{
        transformOrigin: "64px 32px",
        animation: mood === "listening" ? "uxie-wag 0.9s ease-in-out infinite" : "uxie-bob 4s ease-in-out infinite",
      }}>
        <path
          d="M 46 36 C 48 24, 53 18, 56 30 C 58 14, 62 10, 64 24 C 66 10, 70 14, 72 30 C 75 18, 80 24, 82 36 Z"
          fill={accent} stroke={accent} strokeWidth={2} strokeLinejoin="round" opacity={0.95}
        />
        <circle cx="56" cy="27" r="1.3" fill="#fff" opacity={0.8}/>
        <circle cx="64" cy="21" r="1.3" fill="#fff" opacity={0.8}/>
        <circle cx="72" cy="27" r="1.3" fill="#fff" opacity={0.8}/>
      </g>

      {/* feet */}
      <ellipse cx="48" cy="112" rx="7" ry="4" fill={skinShadow} stroke={ink} strokeWidth={1.6}/>
      <ellipse cx="80" cy="112" rx="7" ry="4" fill={skinShadow} stroke={ink} strokeWidth={1.6}/>

      {/* body */}
      <g
        filter={`url(#soft-${uid})`}
        style={{ transformOrigin: "64px 74px", animation: "uxie-breathe 3.4s ease-in-out infinite" }}
      >
        <path
          d="M 24 72 C 24 44, 38 36, 64 36 C 90 36, 104 44, 104 72 C 104 100, 88 112, 64 112 C 40 112, 24 100, 24 72 Z"
          fill={`url(#body-${uid})`} stroke={ink} strokeWidth={1.8}
        />
        <ellipse cx="48" cy="54" rx="24" ry="17" fill={`url(#glow-${uid})`}/>

        {/* cheeks */}
        <ellipse cx="40" cy="80" rx="9" ry="6" fill={`url(#cheek-${uid})`}/>
        <ellipse cx="88" cy="80" rx="9" ry="6" fill={`url(#cheek-${uid})`}/>

        {/* eyes */}
        <g style={{
          animation: mood !== "sleeping" ? "uxie-blink 5.2s ease-in-out infinite" : "none",
          transformOrigin: "52px 66px",
        }}>
          {mood === "sleeping" ? (
            <path d="M 47 66 Q 52 70 57 66" stroke={ink} strokeWidth={2.2} fill="none" strokeLinecap="round"/>
          ) : (
            <>
              <ellipse cx="52" cy="66" rx="4.2" ry={4.8 * eyeR} fill={ink}/>
              <circle cx="53.6" cy="64.4" r="1.4" fill="white"/>
              <circle cx="51"   cy="67.6" r="0.7" fill="white" opacity={0.8}/>
            </>
          )}
        </g>
        <g style={{
          animation: mood !== "sleeping" ? "uxie-blink 5.2s ease-in-out infinite" : "none",
          animationDelay: "0.06s",
          transformOrigin: "76px 66px",
        }}>
          {mood === "sleeping" ? (
            <path d="M 71 66 Q 76 70 81 66" stroke={ink} strokeWidth={2.2} fill="none" strokeLinecap="round"/>
          ) : (
            <>
              <ellipse cx="76" cy="66" rx="4.2" ry={4.8 * eyeR} fill={ink}/>
              <circle cx="77.6" cy="64.4" r="1.4" fill="white"/>
              <circle cx="75"   cy="67.6" r="0.7" fill="white" opacity={0.8}/>
            </>
          )}
        </g>

        {/* mouth */}
        <path
          d={mouth} stroke={ink} strokeWidth={2}
          fill={filled ? ink : ink} strokeLinecap="round" strokeLinejoin="round"
          opacity={filled ? 1 : 0.9}
        />
        {filled && <ellipse cx="64" cy="81" rx="4" ry="2.5" fill={cheek}/>}

        {mood === "sleeping" && (
          <g style={{ animation: "uxie-bob 2s ease-in-out infinite" }}>
            <text x="92"  y="44" fontSize="13" fontFamily="Newsreader, serif" fontWeight={700} fill={ink}>z</text>
            <text x="100" y="36" fontSize="9"  fontFamily="Newsreader, serif" fontWeight={700} fill={ink} opacity={0.6}>z</text>
          </g>
        )}
        {mood === "thinking" && (
          <g opacity={0.8} style={{ animation: "uxie-bob 1.8s ease-in-out infinite" }}>
            <circle cx="96"  cy="44" r="2.2" fill={ink}/>
            <circle cx="102" cy="38" r="1.5" fill={ink} opacity={0.6}/>
            <circle cx="106" cy="32" r="1"   fill={ink} opacity={0.4}/>
          </g>
        )}
      </g>

      {mood !== "sleeping" && (
        <g style={{ animation: "uxie-bob 2.8s ease-in-out infinite" }} opacity={0.7}>
          <path d="M 102 52 L 104 56 L 108 58 L 104 60 L 102 64 L 100 60 L 96 58 L 100 56 Z" fill={accent}/>
        </g>
      )}

      {mood === "listening" && (
        <g stroke={accent} fill="none" strokeWidth={2.2} strokeLinecap="round">
          <path d="M 14 60 Q 8 72 14 82"   style={{ animation: "uxie-breathe 1.1s ease-in-out infinite" }}                 opacity={0.9}/>
          <path d="M 6 54 Q -2 72 6 88"   style={{ animation: "uxie-breathe 1.1s 0.15s ease-in-out infinite" }}            opacity={0.5}/>
          <path d="M 114 60 Q 120 72 114 82" style={{ animation: "uxie-breathe 1.1s 0.05s ease-in-out infinite" }}         opacity={0.9}/>
          <path d="M 122 54 Q 130 72 122 88" style={{ animation: "uxie-breathe 1.1s 0.2s ease-in-out infinite" }}          opacity={0.5}/>
        </g>
      )}
    </svg>
  );
}

/** Tiny logo mark — same visual vocabulary as UxieMascot at favicon scale. */
export function UxieMark({ size = 28, accent = "var(--accent, #d97757)" }: { size?: number; accent?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32">
      <path d="M 9 10 C 10 5, 12 3, 13 8 C 14 3, 15 2, 16 7 C 17 2, 18 3, 19 8 C 20 3, 22 5, 23 10 Z"
        fill={accent} strokeLinejoin="round"/>
      <path d="M 5 20 C 5 13, 9 11, 16 11 C 23 11, 27 13, 27 20 C 27 26, 23 28, 16 28 C 9 28, 5 26, 5 20 Z"
        fill="#faecc8" stroke="#2a1f15" strokeWidth={1.4}/>
      <ellipse cx="9.5"  cy="22" rx="2"   ry="1.4" fill="#f29a92" opacity={0.7}/>
      <ellipse cx="22.5" cy="22" rx="2"   ry="1.4" fill="#f29a92" opacity={0.7}/>
      <ellipse cx="12.5" cy="19" rx="1.8" ry="2"   fill="#2a1f15"/>
      <circle  cx="13.1" cy="18.4" r="0.65" fill="white"/>
      <ellipse cx="19.5" cy="19" rx="1.8" ry="2"   fill="#2a1f15"/>
      <circle  cx="20.1" cy="18.4" r="0.65" fill="white"/>
      <path d="M 14 22.5 Q 16 24.2 18 22.5" stroke="#2a1f15" strokeWidth={1.2} fill="none" strokeLinecap="round"/>
    </svg>
  );
}

/** Decorative waveform — used in the dictate banner and any "audio is flowing" affordance. */
export function Waveform({
  bars = 24,
  color = "currentColor",
  height = 32,
  active = true,
}: { bars?: number; color?: string; height?: number; active?: boolean }) {
  const heights = React.useMemo(
    () => Array.from({ length: bars }, (_, i) => 0.3 + Math.sin(i * 0.6) * 0.3 + Math.random() * 0.4),
    [bars],
  );
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, height }}>
      {heights.map((h, i) => (
        <div key={i} style={{
          width: 3, height: `${h * 100}%`, minHeight: 3,
          background: color, borderRadius: 2,
          transformOrigin: "center",
          animation: active ? `uxie-waveBar ${0.6 + (i % 4) * 0.1}s ease-in-out ${i * 0.05}s infinite` : "none",
          opacity: active ? 1 : 0.4,
        }}/>
      ))}
    </div>
  );
}

/** Custom flame — used in streak hero. Replaces the 🔥 emoji from the v1 design. */
export function Flame({ size = 28, color = "#d36652", inner = "#f2e2a4" }: { size?: number; color?: string; inner?: string }) {
  return (
    <svg width={size} height={size * 1.14} viewBox="0 0 28 32" style={{ display: "inline-block", verticalAlign: "-4px" }}>
      <path
        d="M 14 2 C 8 9, 5 14, 5 20 a 9 9 0 0 0 18 0 c 0 -4 -2 -7 -4 -9 c 1.5 5 -1 8 -3.5 8 c -2 0 -3.5 -1.5 -2 -4.5 c 0.5 -4 2 -7 0.5 -12.5 Z"
        fill={color} stroke="#2a1f15" strokeWidth={1.4} strokeLinejoin="round"
      />
      <path d="M 12 21 C 11 18, 12 15, 14 13 c 1 3 1 5 2 7 a 3 3 0 1 1 -4 1 Z" fill={inner}/>
    </svg>
  );
}
