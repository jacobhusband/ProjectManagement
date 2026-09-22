import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
EDITOR_MAIN_PATH = REPO_ROOT / "project-pages-editor" / "src" / "main.jsx"
EDITOR_STYLE_PATH = REPO_ROOT / "project-pages-editor" / "src" / "styles.css"


class PageEmailAttachmentUiTests(unittest.TestCase):
    @staticmethod
    def _block(text: str, start_marker: str, end_marker: str) -> str:
        start = text.index(start_marker)
        end = text.index(end_marker, start)
        return text[start:end]

    # --- editor node ------------------------------------------------------
    def test_editor_registers_inline_page_email_node(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        self.assertIn("const PageEmail = Node.create({", main)
        node_block = self._block(
            main, "const PageEmail = Node.create({", "const PageWorkbook = Node.create({"
        )
        self.assertIn('name: "pageEmail",', node_block)
        self.assertIn('group: "inline",', node_block)
        self.assertIn("inline: true,", node_block)
        self.assertIn("atom: true,", node_block)
        self.assertIn('{ tag: "span.page-email[data-email-raw]" }', node_block)
        self.assertIn('"data-email-action": "open",', node_block)
        self.assertIn('"data-email-action": "remove",', node_block)
        self.assertIn("insertPageEmail:", node_block)
        # Registered in the extension list or the node never parses.
        self.assertIn("      PageEmail,", main)

    def test_email_ref_shape_round_trips_through_data_attributes(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        attrs_block = self._block(
            main, "const PAGE_EMAIL_ATTRS = [", "function readPageEmailAttrs(element) {"
        )
        for key, attribute in (
            ("raw", "data-email-raw"),
            ("url", "data-email-url"),
            ("label", "data-email-label"),
            ("source", "data-email-source"),
            ("messageId", "data-email-message-id"),
            ("internetMessageId", "data-email-internet-id"),
            ("savedAt", "data-email-saved-at"),
        ):
            self.assertIn(f'["{key}", "{attribute}"]', attrs_block)

    # --- drop handling ----------------------------------------------------
    def test_editor_drop_hands_the_live_data_transfer_to_the_host(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        drop_block = self._block(main, "      handleDrop(view, event) {", "      handleDOMEvents: {")
        # Images keep priority, then the email branch takes over.
        self.assertIn('String(file.type || "").toLowerCase().startsWith("image/")', drop_block)
        self.assertIn(
            "if (!context.onAttachEmailDrop || !looksLikeExternalEmailDrop(event.dataTransfer)) {",
            drop_block,
        )
        self.assertIn(
            "view.posAtCoords({ left: event.clientX, top: event.clientY })", drop_block
        )
        self.assertIn("context.onAttachEmailDrop(event)", drop_block)
        # The DataTransfer must be handed over before the handler yields.
        self.assertLess(
            drop_block.index("event.preventDefault();\n        clearEmailDropTarget(view);\n        //"),
            drop_block.index("context.onAttachEmailDrop(event)"),
        )
        self.assertLess(
            drop_block.index("view.posAtCoords"),
            drop_block.index("context.onAttachEmailDrop(event)"),
        )

    def test_internal_and_link_drags_are_not_claimed(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        gate = self._block(
            main,
            "function looksLikeExternalEmailDrop(dataTransfer) {",
            "function clearEmailDropTarget(view) {",
        )
        self.assertIn('if (types.includes("files")) return true;', gate)
        self.assertIn('type.startsWith("filegroupdescriptor")', gate)
        self.assertIn('type.startsWith("renprivate")', gate)

    def test_dragover_highlights_the_hovered_block(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        dom_events = self._block(main, "      handleDOMEvents: {", "    },\n    onUpdate(")
        self.assertIn("dragover(view, event) {", dom_events)
        self.assertIn('event.dataTransfer.dropEffect = "copy";', dom_events)
        self.assertIn("setEmailDropTarget(view, coords ? coords.pos : null);", dom_events)
        self.assertIn("dragleave(view, event) {", dom_events)
        self.assertIn("clearEmailDropTarget(view);", dom_events)
        self.assertIn(
            'block.classList.add("is-email-drop-target");', main
        )

    def test_chip_lands_at_the_end_of_the_hovered_line(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        insert_block = self._block(
            main,
            "function insertPageEmailAtPos(emailRef, pos) {",
            "function resolveAndInsertEmail(pending, pos) {",
        )
        self.assertIn("while (depth > 0 && !$pos.node(depth).isTextblock) depth -= 1;", insert_block)
        self.assertIn("insertAt = depth > 0 ? $pos.end(depth) : pos;", insert_block)
        self.assertIn(
            'insertContentAt(insertAt, { type: "pageEmail", attrs })', insert_block
        )

    # --- chip actions -----------------------------------------------------
    def test_chip_buttons_open_and_remove_through_the_host(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        click_block = self._block(
            main,
            "  async function handleEditorClick(event) {",
            '    const workbookAction = event.target.closest?.("[data-workbook-action]");',
        )
        self.assertIn('event.target.closest?.("[data-email-action]")', click_block)
        self.assertIn("context.onOpenEmail?.(attrs)", click_block)
        self.assertIn("context.onDeleteEmail?.(attrs)", click_block)
        self.assertIn('const managed = attrs.source === "saved-file";', click_block)
        self.assertIn("if (!window.confirm(confirmation)) return;", click_block)
        self.assertIn('node.type.name === "pageEmail" && node.attrs.raw === attrs.raw', click_block)
        self.assertIn('.setMeta("addToHistory", false)', click_block)

    def test_slash_email_command_offers_a_keyboard_path(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        registry = self._block(main, "const SLASH_COMMANDS = [", "function commandMatches(")
        self.assertIn('{ id: "email", label: "Email", shortcut: "@", group: "media" },', registry)
        execute_block = self._block(
            main,
            "function executeSlashCommand(command) {",
            "function applyColorChoice(value) {",
        )
        self.assertIn('} else if (command.id === "email") {', execute_block)
        self.assertIn("void attachEmailFromPicker();", execute_block)

    # --- host bridge ------------------------------------------------------
    def test_host_probes_outlook_virtual_files_before_giving_up(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        capture_block = self._block(
            script,
            "function captureDropFileEntries(dt) {",
            "const OUTLOOK_DROP_TYPE_PREFIXES = ",
        )
        # dataTransfer.files is always empty for Outlook's virtual files.
        self.assertIn("entry = item.webkitGetAsEntry?.();", capture_block)
        self.assertIn("if (entry?.isFile) entries.push(entry);", capture_block)

        self.assertIn("function captureEmailDropSources(dt) {", script)
        sources_block = self._block(
            script, "function captureEmailDropSources(dt) {", "function readEntryAsFile(entry) {"
        )
        for field in ("files:", "entries:", "urlCandidate:", "types:"):
            self.assertIn(field, sources_block)

        resolve_block = self._block(
            script,
            "async function resolveEmailRefFromCapturedDrop(captured, context = {}) {",
            "async function resolveEmailRefFromDrop(event, context = {}) {",
        )
        self.assertIn('return { emailRef, source: "file-drop" };', resolve_block)
        self.assertIn('return { emailRef, source: "entry-drop" };', resolve_block)
        self.assertIn('return { emailRef, source: "url-drop" };', resolve_block)
        self.assertIn("outlookDrop: looksLikeOutlookDrop(captured.types),", resolve_block)

    def test_existing_drop_call_sites_keep_their_entry_point(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("async function resolveEmailRefFromDrop(event, context = {}) {", script)
        # The deliverable/task/note drop zones must keep working off the same
        # signature after the synchronous-capture refactor.
        self.assertIn("const resolved = await resolveEmailRefFromDrop(e, context);", script)
        self.assertIn("const resolved = await resolveEmailRefFromDrop(\n", script)
        wrapper = self._block(
            script,
            "async function resolveEmailRefFromDrop(event, context = {}) {",
            "async function promptForEmailLinkRef() {",
        )
        self.assertIn("captureEmailDropSources(event?.dataTransfer)", wrapper)
        self.assertIn("return resolveEmailRefFromCapturedDrop(captured, context);", wrapper)

    def test_page_drop_falls_back_to_the_outlook_selection(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        page_block = self._block(
            script,
            "async function resolvePageEmailDropRef(event, context = {}) {",
            "async function requestPageEmailRef(context = {}) {",
        )
        # Capture must happen before the first await.
        self.assertLess(
            page_block.index("captureEmailDropSources(event?.dataTransfer)"),
            page_block.index("await resolveEmailRefFromCapturedDrop"),
        )
        self.assertIn("const outlookDrop = looksLikeOutlookDrop(captured?.types);", page_block)
        self.assertIn("if (outlookDrop || (unreadableFileDrop &&", page_block)
        self.assertIn("await saveActiveOutlookSelectionRef(context)", page_block)
        self.assertIn("Type /email in your notes", page_block)
        self.assertIn(
            "window.pywebview.api.save_active_outlook_selection(context)", script
        )

    def test_editor_context_exposes_the_email_callbacks(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        bridge = self._block(
            script,
            "function setProjectPagesEditorDocument(context) {",
            "function renderPageView() {",
        )
        self.assertIn(
            "onAttachEmailDrop: (event) => resolvePageEmailDropRef(event, buildPageEmailDropContext()),",
            bridge,
        )
        self.assertIn("onPickEmail: () => requestPageEmailRef(buildPageEmailDropContext()),", bridge)
        self.assertIn("onOpenEmail: (attrs) => openPageEmailRef(attrs),", bridge)
        self.assertIn("onDeleteEmail: (attrs) => deletePageEmailRef(attrs),", bridge)

    def test_page_email_helpers_reuse_the_existing_email_pipeline(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("function buildPageEmailDropContext() {", script)
        context_block = self._block(
            script,
            "function buildPageEmailDropContext() {",
            "async function resolvePageEmailDropRef(event, context = {}) {",
        )
        self.assertIn('deliverableId: String(pageEditorOwnerKey || "page").trim(),', context_block)
        self.assertIn('scope: "page-editor",', context_block)

        open_block = self._block(
            script,
            "async function openPageEmailRef(attrs) {",
            "async function deletePageEmailRef(attrs) {",
        )
        self.assertIn("await openDeliverableEmailRef(ref)", open_block)

        delete_block = self._block(
            script, "async function deletePageEmailRef(attrs) {", "\n\nfunction openExternalUrl("
        )
        # Only managed copies are ours to delete.
        self.assertIn("await deleteManagedSavedEmailRef(ref)", delete_block)

    def test_chip_text_is_kept_out_of_the_important_rollup(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        reader = self._block(
            script,
            "function readImportantNodeText(node) {",
            "function extractImportantPageLines(html, source) {",
        )
        self.assertIn('if (node.querySelector(".page-email")) {', reader)
        self.assertIn(
            'target.querySelectorAll(".page-email").forEach((chip) => chip.remove());', reader
        )
        self.assertIn("text: readImportantNodeText(node),", script)

    # --- styles and bundle ------------------------------------------------
    def test_chip_and_drop_target_are_styled(self):
        css = EDITOR_STYLE_PATH.read_text(encoding="utf-8")
        self.assertIn(".project-pages-editor-content .page-email {", css)
        self.assertIn(".project-pages-editor-content .page-email-icon {", css)
        self.assertIn(".project-pages-editor-content .page-email-label {", css)
        self.assertIn(".project-pages-editor-content .page-email-action {", css)
        self.assertIn(".project-pages-editor-content .page-email.is-unavailable {", css)
        self.assertIn(".project-pages-editor-content .is-email-drop-target {", css)

    def test_built_bundle_includes_the_email_node(self):
        bundle = (
            REPO_ROOT / "project-pages-editor" / "dist" / "project-pages-editor.js"
        ).read_text(encoding="utf-8", errors="ignore")
        # A stale dist/ silently ships the old editor, so guard the rebuild.
        self.assertIn("pageEmail", bundle)
        self.assertIn("data-email-raw", bundle)

        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        self.assertIn("project-pages-editor/dist/project-pages-editor.js?v=", html)
        self.assertNotIn("project-pages-editor.js?v=20260708-richer-blocks-p6", html)


if __name__ == "__main__":
    unittest.main()
