import { useEffect, useState } from "react";

/**
 * Returns `value`, but only after it has stopped changing for `delay` ms.
 * Works best with strings or numbers: an object that's rebuilt on every
 * render counts as a change every time and restarts the timer.
 */
export function useDebouncedValue(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
