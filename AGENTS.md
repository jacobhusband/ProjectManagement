# Adding deliverables to ACIES Project Management

When the user asks to add a deliverable, update the app's project data; this is an operational data task, not a request to change application code.

## Locate the project and source

- On this Windows installation, the active project list is `%USERPROFILE%\Documents\ProjectManagementApp\tasks.json`. Confirm against `main.py:get_app_data_dir` and `TASKS_FILE` if the app changes. Do not substitute the redirected OneDrive Documents folder returned by the Windows known-folder API.
- The file contains a JSON array of projects. Match the intended project by its `id`, `name`, and, when useful, `path`. Add to that project's `deliverables` array. Check for an existing matching deliverable before creating one.
- For email-based requests, use the Outlook Email connector to find the relevant recent email. Use its subject, sender, received date, and available content to establish scope and timing. Include useful source context and the Outlook message link in a deliverable note.
- Distinguish an expected request date from a delivery deadline. Leave `due` and `hardDue` blank when no deadline is stated. Do not invent scope or promise a delivery date.

## Save safely

- Prefer the app's supported workflow when available: `createDeliverable(seed)`, append to `project.deliverables`, then `await save()`. The Add Deliverable command asks for description, soft due date, and hard due date; either date may be skipped.
- When directly editing the data file, ensure the app is closed to prevent its in-memory state from overwriting the edit. If its state is uncertain, ask whether it is closed or use an authorized live app workflow.
- Re-read the latest file immediately before the edit. Preserve a byte-for-byte backup in an appropriate local backup location. Add only the requested deliverable and preserve every existing project and field.
- Match the current schema in `script.js:createDeliverable` and `normalizeDeliverable`; do not import `main.py` just to inspect constants because importing may initialize app resources.
- Use a new `dlv_` UUID. Typical fields: `name`, `due`, `hardDue`, `notes`, `page`, `noteItems`, `tasks`, migration flags, `statuses`, `statusTags`, `status`, attachment/link/email fields, pinning fields, workroom fields, `appliedChecklists`, and `checklistContext`.
- Keep notes consistent between `notes` and `noteItems`, and keep all status representations consistent. For a deliverable awaiting a formal request, `status: "Waiting"`, `statuses: ["Waiting"]`, and `statusTags: ["waiting"]` are appropriate. Use the context to choose other statuses.
- Store due dates in the app's current format (normally `MM/DD/YYYY`), or an empty string. A note item normally has `text`, `pinned`, `dueDate`, `attachments`, `links`, `emailRefs`, and `emailRef`.
- Before replacement, assert that removing the newly appended deliverable reproduces the original parsed data exactly. Check that the file has not changed since it was read. Write to a temporary file in the same directory, flush it, and replace atomically.
- Request sandbox escalation through the execution tool if the app data directory is outside writable roots. The user's request authorizes the deliverable addition; do not ask for redundant task confirmation.
- Re-read the saved file and verify the new deliverable, project ID, status, dates, and preservation of existing data. Report completion concisely.

## Confirmed example

On November 11, 2026, project `251406` (BofA - Peppertree Plaza, 5590 W. Sample Rd., Margate, FL) received a `Record Documents` deliverable with status `Waiting` and blank due dates. Joseph Omole's email said the final invoice and record documents request was expected before mid-next week; it did not set a delivery deadline. The update was verified after saving, with all existing records preserved. Treat this as an example, not a default project or deadline for future requests.
