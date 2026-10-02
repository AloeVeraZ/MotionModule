/* Shared JSON transport. A stalled link must eventually fail so the pages
   can disarm and show connection loss, then retry on their next poll. */
function createJSONClient(timeoutMs = 8000) {
  return async function jsonFetch(url, options = {}) {
    const {timeoutMs: limit = timeoutMs, ...fetchOptions} = options;
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener('abort', abort, {once: true});
    const timer = setTimeout(abort, limit);
    try {
      const response = await fetch(url, {cache: 'no-store', ...fetchOptions, signal: controller.signal});
      const data = await response.json().catch(error => {
        if (controller.signal.aborted) throw error;
        return {error: `HTTP ${response.status}`};
      });
      if (!response.ok) {
        const error = new Error(data.error || `Request failed (${response.status})`);
        error.status = response.status;
        error.data = data;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener('abort', abort);
    }
  };
}
