import { useEffect, useState } from "react";

// Matches Tailwind's `md` breakpoint. Rendering one layout (not two hidden by CSS) keeps a
// single copy of each order and editor in the page.
const QUERY = "(min-width: 768px)";

export function useIsWide(): boolean {
  const [wide, setWide] = useState(() => typeof window !== "undefined" && window.matchMedia(QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    const update = () => setWide(mq.matches);
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return wide;
}
