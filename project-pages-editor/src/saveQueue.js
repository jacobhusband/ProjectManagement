// One writer and one debounce timer; a completed write only acknowledges the
// revision it started with. Failed writes stay dirty until explicitly retried.
export function createSaveQueue({ persist, onStatus = () => {}, delay = 700 }) {
  let revision = 0;
  let savedRevision = 0;
  let timer = null;
  let running = null;
  function cancelTimer() {
    clearTimeout(timer);
    timer = null;
  }
  async function drain() {
    while (savedRevision < revision) {
      const writing = revision;
      onStatus("Saving...");
      try {
        if (await persist() === false) throw new Error("Save failed");
      } catch (_) {
        onStatus("Save failed");
        return false;
      }
      savedRevision = writing;
    }
    onStatus("Saved");
    return true;
  }
  function flush() {
    cancelTimer();
    if (!running) {
      running = drain().finally(() => { running = null; });
    }
    return running;
  }
  function dirty() {
    revision += 1;
    onStatus("Unsaved changes");
    cancelTimer();
    timer = setTimeout(flush, delay);
  }
  return { dirty, flush, get isDirty() { return savedRevision < revision; } };
}
