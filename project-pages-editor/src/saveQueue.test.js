import assert from "node:assert/strict";
import test from "node:test";
import { createSaveQueue } from "./saveQueue.js";

test("edits arriving during a save are written in order before Saved", async () => {
  const resolvers = [], writes = [], statuses = [];
  let content = "first";
  const queue = createSaveQueue({ delay: 60000, onStatus: (s) => statuses.push(s), persist: () => {
    writes.push(content);
    return new Promise((resolve) => resolvers.push(resolve));
  } });
  queue.dirty();
  const first = queue.flush();
  content = "second";
  queue.dirty();
  const second = queue.flush();
  assert.equal(first, second);
  resolvers.shift()(true);
  await Promise.resolve();
  assert.deepEqual(writes, ["first", "second"]);
  assert.ok(!statuses.includes("Saved"));
  resolvers.shift()(true);
  assert.equal(await first, true);
  assert.equal(queue.isDirty, false);
  assert.equal(statuses.at(-1), "Saved");
});

test("failed saves stay dirty and can be retried", async () => {
  let success = false, writes = 0;
  const statuses = [];
  const queue = createSaveQueue({ onStatus: (s) => statuses.push(s), persist: async () => { writes++; return success; } });
  queue.dirty();
  assert.equal(await queue.flush(), false);
  assert.equal(queue.isDirty, true);
  assert.equal(statuses.at(-1), "Save failed");
  success = true;
  assert.equal(await queue.flush(), true);
  assert.equal(queue.isDirty, false);
  await queue.flush();
  assert.equal(writes, 2);
});

test("multiple keystrokes produce one debounced write", async () => {
  let writes = 0;
  const queue = createSaveQueue({ delay: 5, persist: async () => { writes++; return true; } });
  queue.dirty(); queue.dirty(); queue.dirty();
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(writes, 1);
  assert.equal(queue.isDirty, false);
});
