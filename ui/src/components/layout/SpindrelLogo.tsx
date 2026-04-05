/**
 * Spindrel logo — a triskelion vortex mark.
 * Three curved arms spiral outward from a center dot,
 * evoking spinning/weaving. Monochrome, adapts to theme.
 */
export function SpindrelLogo({ size = 20, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle cx="12" cy="12" r="1.5" fill={color} />
      <path
        d="M12 10 Q16 6 19 9"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M13.7 13 Q16 17.5 11.5 19"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M10.3 12.5 Q5.5 13 5.5 8"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}
