export interface DecadeBucket { decade: number; count: number; }
export interface RidgeRow { label: string; weight: number; peak: boolean; count: number; }

export function toRidgeRows(buckets: DecadeBucket[]): RidgeRow[] {
  if (buckets.length === 0) return [];
  const max = Math.max(1, ...buckets.map(b => b.count));
  const peakBucket = buckets.reduce<DecadeBucket>(
    (a, b) => (b.count > a.count ? b : a),
    buckets[0]!,
  );
  const peakDecade = peakBucket.decade;
  return buckets.map(b => ({
    label: `${b.decade}s`, weight: b.count / max, peak: b.decade === peakDecade, count: b.count,
  }));
}
