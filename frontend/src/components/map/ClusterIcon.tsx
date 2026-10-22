export function clusterTierSize(count: number): number {
  if (count > 100) return 50;
  if (count >= 20) return 40;
  return 30;
}

interface ClusterIconProps {
  count: number;
}

export function ClusterIcon({ count }: ClusterIconProps) {
  const size = clusterTierSize(count);
  return (
    <div
      aria-hidden="true"
      style={{ width: size, height: size }}
      className="flex items-center justify-center rounded-full border border-primary bg-background/55 font-mono text-xs font-semibold tabular-nums text-primary shadow-md backdrop-blur-sm"
    >
      {count}
    </div>
  );
}
