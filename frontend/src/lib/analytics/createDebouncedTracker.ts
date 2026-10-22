export interface DebouncedTracker {
  (): void;
  cancel: () => void;
}

export function createDebouncedTracker(
  fn: () => void,
  delayMs: number,
): DebouncedTracker {
  let timer: ReturnType<typeof setTimeout> | null = null;

  const tracker = (() => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn();
    }, delayMs);
  }) as DebouncedTracker;

  tracker.cancel = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  return tracker;
}
