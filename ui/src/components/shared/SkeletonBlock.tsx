export function SkeletonBlock({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={`bg-skeleton animate-pulse rounded ${className}`}
      style={style}
    />
  );
}
