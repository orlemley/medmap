import { useEffect, useState } from "react";
import { getOptimize } from "../lib/api.js";
import { EMPTY_FC } from "../lib/constants.js";

/**
 * Calls the Stage 8 optimization endpoint whenever `params` changes. A newer request aborts the
 * older one, so a slow response can never overwrite a newer result.
 * On error the previous candidates stay on screen.
 */
export function useOptimize(params) {
  const [state, setState] = useState({ status: "loading", candidates: EMPTY_FC, meta: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, status: "loading", error: null }));
    getOptimize(params, controller.signal)
      .then((data) => setState({ status: "ok", candidates: data.candidates, meta: data.meta, error: null }))
      .catch((error) => {
        if (error.name !== "AbortError") setState((s) => ({ ...s, status: "error", error }));
      });
    return () => controller.abort();
  }, [params]);

  return state;
}
