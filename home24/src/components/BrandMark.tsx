export function BrandMark({ small, onDark }: { small?: boolean; onDark?: boolean }) {
  const s = small ? 26 : 34;
  return (
    <svg width={s} height={s} viewBox="0 0 34 34" aria-hidden>
      <rect x="0.75" y="0.75" width="32.5" height="32.5" fill="none" stroke="#9a7b4f" strokeWidth="1.2" />
      <text
        x="17"
        y="22.5"
        textAnchor="middle"
        fill={onDark ? "#efe8dc" : "#1a1612"}
        fontFamily="Georgia, serif"
        fontSize="11"
        fontWeight="600"
        letterSpacing="0.5"
      >
        H24
      </text>
    </svg>
  );
}
