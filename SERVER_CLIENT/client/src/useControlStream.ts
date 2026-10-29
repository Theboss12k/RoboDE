import { useCallback, useEffect, useRef, useState } from "react";

/** One request in flight, one replaceable target; never replay a drag backlog. */
export function useControlStream<T, R>(options: {
  scope: string | null;
  enabled: boolean;
  send: (target: T) => Promise<R>;
  onFeedback: (feedback: R) => void;
  onError: (error: Error) => void;
}) {
  const handlers = useRef(options);
  handlers.current = options;
  const alive = useRef(true);
  const pending = useRef<{ scope: string; target: T } | null>(null);
  const flight = useRef<Promise<void> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generation = useRef(0);
  const revision = useRef(0);
  const lastSent = useRef(0);
  const active = useRef(false);
  const [busy, setBusy] = useState(false);
  const schedule = useRef<() => void>(() => {});
  const mark = useCallback((value: boolean) => {
    active.current = value;
    if (alive.current) setBusy(value);
  }, []);
  const cancel = useCallback(() => {
    generation.current++;
    revision.current++;
    pending.current = null;
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    mark(flight.current !== null);
  }, [mark]);
  schedule.current = () => {
    if (flight.current || timer.current !== null || !pending.current) return;
    timer.current = setTimeout(
      () => {
        timer.current = null;
        const job = pending.current;
        pending.current = null;
        if (
          !job ||
          job.scope !== handlers.current.scope ||
          !handlers.current.enabled
        ) {
          mark(false);
          return;
        }
        const epoch = generation.current;
        lastSent.current = performance.now();
        flight.current = (async () => {
          try {
            // Install the in-flight promise before calling a sender that may
            // throw synchronously, and recheck cancellation before dispatch.
            await Promise.resolve();
            if (
              !alive.current ||
              epoch !== generation.current ||
              job.scope !== handlers.current.scope ||
              !handlers.current.enabled
            )
              return;
            const result = await handlers.current.send(job.target);
            if (
              alive.current &&
              epoch === generation.current &&
              job.scope === handlers.current.scope
            )
              handlers.current.onFeedback(result);
          } catch (error) {
            if (
              alive.current &&
              epoch === generation.current &&
              job.scope === handlers.current.scope
            ) {
              pending.current = null;
              handlers.current.onError(error as Error);
            }
          } finally {
            flight.current = null;
            if (pending.current && alive.current) schedule.current();
            else mark(false);
          }
        })();
      },
      Math.max(0, 50 - (performance.now() - lastSent.current)),
    );
  };
  const enqueue = useCallback(
    (target: T) => {
      const { scope, enabled } = handlers.current;
      if (!scope || !enabled || !alive.current) return;
      revision.current++;
      pending.current = { scope, target };
      mark(true);
      schedule.current();
    },
    [mark],
  );
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      cancel();
    };
  }, [cancel]);
  useEffect(() => {
    cancel();
  }, [options.scope, options.enabled, cancel]);
  return { enqueue, cancel, busy, active, revision };
}
