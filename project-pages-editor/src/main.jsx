import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import { Extension, Node, mergeAttributes } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import Color from "@tiptap/extension-color";
import { Details, DetailsContent, DetailsSummary } from "@tiptap/extension-details";
import Highlight from "@tiptap/extension-highlight";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import { TableKit } from "@tiptap/extension-table";
import TaskItem from "@tiptap/extension-task-item";
import TaskList from "@tiptap/extension-task-list";
import { TextStyle } from "@tiptap/extension-text-style";
import Underline from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { createLowlight } from "lowlight";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import "./styles.css";
import { selectionWouldDeleteWorkbook } from "./workbookProtection.js";

const lowlight = createLowlight();
lowlight.register({ bash, css, javascript, json, python, sql, typescript, xml });

const CODE_LANGUAGES = [
  { label: "Plain text", value: "" },
  { label: "Bash", value: "bash" },
  { label: "CSS", value: "css" },
  { label: "HTML/XML", value: "xml" },
  { label: "JavaScript", value: "javascript" },
  { label: "JSON", value: "json" },
  { label: "Python", value: "python" },
  { label: "SQL", value: "sql" },
  { label: "TypeScript", value: "typescript" },
];

let root = null;
let mountedContainer = null;
let currentContext = null;
let currentOptions = {};
let flushCurrentEditor = null;
const listeners = new Set();

function emitContext() {
  listeners.forEach((listener) => listener(currentContext));
}

function subscribe(listener) {
  listeners.add(listener);
  listener(currentContext);
  return () => listeners.delete(listener);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read file."));
    reader.readAsDataURL(file);
  });
}

function stripTransientPageHtml(html) {
  const doc = new DOMParser().parseFromString(`<div>${html || ""}</div>`, "text/html");
  const rootEl = doc.body.firstElementChild;
  rootEl.querySelectorAll("mark.page-find-match").forEach((mark) => {
    mark.replaceWith(doc.createTextNode(mark.textContent || ""));
  });
  rootEl.querySelectorAll("img").forEach((img) => {
    img.classList.add("page-inline-image");
    img.classList.remove("is-selected");
    if (img.dataset.asset || img.getAttribute("data-asset")) {
      img.removeAttribute("src");
    }
  });
  rootEl.querySelectorAll("a.page-wiki-link").forEach((link) => {
    link.classList.remove("is-broken");
    link.removeAttribute("title");
    link.setAttribute("contenteditable", "false");
  });
  return rootEl.innerHTML;
}

const PAGE_EMAIL_DROP_BLOCK_SELECTOR = "p, h1, h2, h3, li, blockquote, td, th, pre";

// Only claim drops that carry real payload. Internal ProseMirror drags (moving a
// selection) and plain link drops must keep falling through to the default handling.
function looksLikeExternalEmailDrop(dataTransfer) {
  const types = Array.from(dataTransfer?.types || []).map((type) => String(type).toLowerCase());
  if (types.includes("files")) return true;
  return types.some(
    (type) => type.startsWith("filegroupdescriptor") || type.startsWith("renprivate") ||
      type.startsWith("filecontents") || type.startsWith("application/x-moz-file-promise")
  );
}

function clearEmailDropTarget(view) {
  const marked = view?.dom?.querySelectorAll?.(".is-email-drop-target");
  if (!marked) return;
  Array.from(marked).forEach((element) => element.classList.remove("is-email-drop-target"));
}

function setEmailDropTarget(view, pos) {
  clearEmailDropTarget(view);
  if (!view || !Number.isInteger(pos) || pos < 0 || pos > view.state.doc.content.size) return;
  let domAt = null;
  try {
    domAt = view.domAtPos(pos);
  } catch (_) {
    return;
  }
  const node = domAt?.node?.nodeType === 1 ? domAt.node : domAt?.node?.parentElement;
  const block = node?.closest?.(PAGE_EMAIL_DROP_BLOCK_SELECTOR);
  if (block && view.dom.contains(block)) block.classList.add("is-email-drop-target");
}

function getActiveBlockRect(editor, selector) {
  const { $from } = editor.state.selection;
  const domAt = editor.view.domAtPos($from.pos);
  const element = domAt.node.nodeType === 1 ? domAt.node : domAt.node.parentElement;
  return element?.closest?.(selector)?.getBoundingClientRect() || null;
}

function detectSlashQuery(editor) {
  if (!editor) return null;
  const { state } = editor;
  const { selection } = state;
  if (!selection.empty) return null;
  const $from = selection.$from;
  const before = $from.parent.textBetween(0, $from.parentOffset, "\n", "\0");
  const match = before.match(/(?:^|\s)\/([a-z0-9 ]*)$/i);
  if (!match) return null;
  const query = match[1] || "";
  const from = $from.pos - query.length - 1;
  return {
    query,
    range: { from, to: $from.pos },
    pos: editor.view.coordsAtPos($from.pos),
  };
}

function detectPageLinkQuery(editor) {
  if (!editor) return null;
  const { state } = editor;
  const { selection } = state;
  if (!selection.empty) return null;
  const $from = selection.$from;
  const before = $from.parent.textBetween(0, $from.parentOffset, "\n", "\0");
  const match = before.match(/\[\[([^\]\[]*)$/);
  if (!match) return null;
  const query = match[1] || "";
  const from = $from.pos - query.length - 2;
  return {
    query,
    range: { from, to: $from.pos },
    pos: editor.view.coordsAtPos($from.pos),
  };
}

const PageImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      assetPath: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-asset"),
        renderHTML: (attributes) =>
          attributes.assetPath ? { "data-asset": attributes.assetPath } : {},
      },
      widthPercent: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-width-percent"),
        renderHTML: (attributes) =>
          attributes.widthPercent ? { "data-width-percent": attributes.widthPercent } : {},
      },
      class: {
        default: "page-inline-image",
        parseHTML: (element) => element.getAttribute("class") || "page-inline-image",
        renderHTML: (attributes) => ({ class: attributes.class || "page-inline-image" }),
      },
      style: {
        default: null,
        parseHTML: (element) => element.getAttribute("style"),
        renderHTML: (attributes) => (attributes.style ? { style: attributes.style } : {}),
      },
    };
  },
});

const PageAttachment = Node.create({
  name: "pageAttachment",
  group: "inline",
  inline: true,
  atom: true,
  addAttributes() {
    return {
      type: { default: "path", parseHTML: (element) => element.getAttribute("data-attachment-type") || "path" },
      target: { default: "", parseHTML: (element) => element.getAttribute("data-attachment-target") || "" },
      description: { default: "Open file", parseHTML: (element) => element.textContent || "Open file" },
    };
  },
  parseHTML() { return [{ tag: "span.page-attachment[data-attachment-target]" }]; },
  renderHTML({ HTMLAttributes }) {
    return ["span", {
      class: "page-attachment", contenteditable: "false", role: "button", tabindex: "0",
      "data-attachment-type": HTMLAttributes.type,
      "data-attachment-target": HTMLAttributes.target,
    }, HTMLAttributes.description];
  },
});

const PageLink = Node.create({
  name: "pageLink",
  group: "inline",
  inline: true,
  atom: true,
  selectable: false,

  addAttributes() {
    return {
      pageId: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-page-id") || "",
      },
      title: {
        default: "Untitled",
        parseHTML: (element) => element.textContent || "Untitled",
      },
    };
  },

  parseHTML() {
    return [{ tag: "a.page-wiki-link[data-page-id]" }];
  },

  renderHTML({ HTMLAttributes }) {
    const title = HTMLAttributes.title || "Untitled";
    return [
      "a",
      mergeAttributes({
        class: "page-wiki-link",
        href: "#",
        "data-page-id": HTMLAttributes.pageId,
        contenteditable: "false",
      }),
      title,
    ];
  },

  addCommands() {
    return {
      insertPageLink:
        (attrs) =>
        ({ chain }) =>
          chain().insertContent({ type: this.name, attrs }).run(),
    };
  },
});

// Mirrors the host's emailRef shape (normalizeEmailRef in script.js) flattened onto
// data-* attributes: a page is persisted as one HTML blob, so there is nowhere else
// for the reference to live.
const PAGE_EMAIL_ATTRS = [
  ["raw", "data-email-raw"],
  ["url", "data-email-url"],
  ["label", "data-email-label"],
  ["source", "data-email-source"],
  ["messageId", "data-email-message-id"],
  ["internetMessageId", "data-email-internet-id"],
  ["savedAt", "data-email-saved-at"],
];

function readPageEmailAttrs(element) {
  const attrs = {};
  PAGE_EMAIL_ATTRS.forEach(([key, attribute]) => {
    attrs[key] = element?.getAttribute?.(attribute) || "";
  });
  return attrs;
}

const PageEmail = Node.create({
  name: "pageEmail",
  group: "inline",
  inline: true,
  atom: true,
  selectable: false,

  addAttributes() {
    const attributes = {};
    PAGE_EMAIL_ATTRS.forEach(([key, attribute]) => {
      attributes[key] = {
        default: "",
        parseHTML: (element) => element.getAttribute(attribute) || "",
      };
    });
    return attributes;
  },

  parseHTML() {
    return [{ tag: "span.page-email[data-email-raw]" }];
  },

  renderHTML({ HTMLAttributes }) {
    const dataAttrs = { class: "page-email", contenteditable: "false" };
    PAGE_EMAIL_ATTRS.forEach(([key, attribute]) => {
      dataAttrs[attribute] = HTMLAttributes[key] || "";
    });
    const label = HTMLAttributes.label || "Email";
    return [
      "span",
      mergeAttributes(dataAttrs),
      ["span", { class: "page-email-icon", "aria-hidden": "true" }, "@"],
      [
        "button",
        {
          type: "button",
          class: "page-email-label",
          "data-email-action": "open",
          title: `Open ${label}`,
        },
        label,
      ],
      [
        "button",
        {
          type: "button",
          class: "page-email-action page-email-remove",
          "data-email-action": "remove",
          title: "Remove email",
          "aria-label": "Remove email",
        },
        "x",
      ],
    ];
  },

  addCommands() {
    return {
      insertPageEmail:
        (attrs) =>
        ({ chain }) =>
          chain().insertContent({ type: this.name, attrs }).run(),
    };
  },
});

const PageWorkbook = Node.create({
  name: "pageWorkbook",
  group: "block",
  atom: true,
  selectable: false,
  draggable: false,
  isolating: true,

  addAttributes() {
    return {
      fileRef: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-page-file") || "",
      },
      fileName: {
        default: "Workbook.xlsx",
        parseHTML: (element) => element.getAttribute("data-file-name") || "Workbook.xlsx",
      },
      storageType: {
        default: "managed",
        parseHTML: (element) => element.getAttribute("data-file-storage") || "managed",
      },
    };
  },

  parseHTML() {
    return [{ tag: "div.page-workbook[data-page-file]" }];
  },

  renderHTML({ HTMLAttributes }) {
    const fileRef = HTMLAttributes.fileRef || "";
    const fileName = HTMLAttributes.fileName || "Workbook.xlsx";
    const storageType = HTMLAttributes.storageType === "external" ? "external" : "managed";
    return [
      "div",
      mergeAttributes({
        class: "page-workbook",
        "data-page-file": fileRef,
        "data-file-name": fileName,
        "data-file-storage": storageType,
        contenteditable: "false",
      }),
      ["span", { class: "page-workbook-icon", "aria-hidden": "true" }, "X"],
      [
        "span",
        { class: "page-workbook-copy" },
        ["span", { class: "page-workbook-name" }, fileName],
        [
          "span",
          { class: "page-workbook-status", "aria-live": "polite" },
          storageType === "external" ? "Checking linked file..." : "Checking availability...",
        ],
      ],
      [
        "span",
        { class: "page-workbook-actions" },
        [
          "button",
          {
            type: "button",
            class: "page-workbook-action",
            "data-workbook-action": "open",
            disabled: "disabled",
          },
          "Open",
        ],
        [
          "button",
          {
            type: "button",
            class: "page-workbook-action page-workbook-delete",
            "data-workbook-action": "delete",
          },
          storageType === "external" ? "Remove link" : "Delete",
        ],
      ],
    ];
  },

  addCommands() {
    return {
      insertPageWorkbook:
        (attrs) =>
        ({ chain }) =>
          chain().insertContent({ type: this.name, attrs }).run(),
    };
  },
});

const CALLOUT_EMOJIS = ["💡", "📌", "⚠️", "✅", "❓", "🔥"];
const CALLOUT_COLORS = ["gray", "blue", "green", "yellow", "red", "purple"];

const PageCallout = Node.create({
  name: "pageCallout",
  group: "block",
  content: "paragraph+",
  defining: true,

  addAttributes() {
    return {
      color: {
        default: "gray",
        parseHTML: (element) => element.getAttribute("data-callout-color") || "gray",
        renderHTML: (attributes) => ({ "data-callout-color": attributes.color || "gray" }),
      },
      emoji: {
        default: "💡",
        parseHTML: (element) => element.getAttribute("data-callout-emoji") || "💡",
        renderHTML: (attributes) => ({ "data-callout-emoji": attributes.emoji || "💡" }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div.page-callout" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes({ class: "page-callout" }, HTMLAttributes), 0];
  },

  addCommands() {
    return {
      setCallout:
        (attrs = {}) =>
        ({ commands }) =>
          commands.wrapIn(this.name, attrs),
      updateCalloutAttrs:
        (attrs) =>
        ({ commands }) =>
          commands.updateAttributes(this.name, attrs),
    };
  },

  addKeyboardShortcuts() {
    return {
      "Mod-Enter": () => {
        const { state } = this.editor;
        const { $from } = state.selection;
        for (let depth = $from.depth; depth > 0; depth -= 1) {
          if ($from.node(depth).type.name === this.name) {
            const pos = $from.after(depth);
            return this.editor
              .chain()
              .insertContentAt(pos, { type: "paragraph" })
              .focus(pos + 1)
              .run();
          }
        }
        return false;
      },
    };
  },
});

const IMPORTANT_BLOCK_TYPES = ["paragraph", "heading"];
const pageImportantPluginKey = new PluginKey("pageImportant");

function findImportantBlock($from) {
  for (let depth = $from.depth; depth >= 0; depth -= 1) {
    const node = $from.node(depth);
    if (IMPORTANT_BLOCK_TYPES.includes(node.type.name)) {
      return { node, pos: $from.before(depth) };
    }
  }
  return null;
}

function buildImportantFlagDom(view, getPos) {
  const flag = document.createElement("span");
  flag.className = "page-important-flag";
  flag.setAttribute("contenteditable", "false");
  flag.setAttribute("role", "button");
  flag.setAttribute("tabindex", "-1");
  flag.setAttribute("title", "Important - click to clear");
  flag.setAttribute("aria-label", "Important - click to clear");
  flag.textContent = "!";
  flag.addEventListener("mousedown", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const pos = typeof getPos === "function" ? getPos() : null;
    if (pos == null) return;
    const $pos = view.state.doc.resolve(pos);
    const blockPos = $pos.before($pos.depth);
    view.dispatch(view.state.tr.setNodeAttribute(blockPos, "important", false));
    view.focus();
  });
  return flag;
}

const PageImportant = Extension.create({
  name: "pageImportant",

  addGlobalAttributes() {
    return [
      {
        types: IMPORTANT_BLOCK_TYPES,
        attributes: {
          important: {
            default: false,
            keepOnSplit: false,
            parseHTML: (element) => element.getAttribute("data-important") === "true",
            renderHTML: (attributes) =>
              attributes.important
                ? { "data-important": "true", class: "page-important" }
                : {},
          },
        },
      },
    ];
  },

  addCommands() {
    return {
      setImportant:
        (value) =>
        ({ state, tr, dispatch }) => {
          const block = findImportantBlock(state.selection.$from);
          if (!block) return false;
          if (dispatch) tr.setNodeAttribute(block.pos, "important", !!value);
          return true;
        },
      toggleImportant:
        () =>
        ({ state, tr, dispatch }) => {
          const block = findImportantBlock(state.selection.$from);
          if (!block) return false;
          if (dispatch) {
            tr.setNodeAttribute(block.pos, "important", !block.node.attrs.important);
          }
          return true;
        },
    };
  },

  addKeyboardShortcuts() {
    return {
      "Mod-Alt-i": () => this.editor.commands.toggleImportant(),
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: pageImportantPluginKey,
        props: {
          decorations(state) {
            const decorations = [];
            state.doc.descendants((node, pos) => {
              if (!node.isTextblock || !node.attrs?.important) return;
              decorations.push(
                Decoration.widget(pos + 1, buildImportantFlagDom, {
                  side: -1,
                  key: "page-important-flag",
                  ignoreSelection: true,
                  stopEvent: () => true,
                })
              );
            });
            return decorations.length ? DecorationSet.create(state.doc, decorations) : null;
          },
        },
      }),
    ];
  },
});

const TEXT_COLORS = [
  { label: "Default", value: null },
  { label: "Gray", value: "#9b9a97" },
  { label: "Brown", value: "#a8775c" },
  { label: "Orange", value: "#d9730d" },
  { label: "Yellow", value: "#c29343" },
  { label: "Green", value: "#4d9968" },
  { label: "Blue", value: "#3f83c8" },
  { label: "Purple", value: "#9d68d3" },
  { label: "Pink", value: "#d5598f" },
  { label: "Red", value: "#e03e3e" },
];

const HIGHLIGHT_COLORS = [
  { label: "Default", value: null },
  { label: "Gray", value: "rgba(148, 163, 184, 0.35)" },
  { label: "Brown", value: "rgba(180, 130, 90, 0.35)" },
  { label: "Orange", value: "rgba(251, 146, 60, 0.35)" },
  { label: "Yellow", value: "rgba(250, 204, 21, 0.4)" },
  { label: "Green", value: "rgba(74, 222, 128, 0.35)" },
  { label: "Blue", value: "rgba(96, 165, 250, 0.35)" },
  { label: "Purple", value: "rgba(192, 132, 252, 0.35)" },
  { label: "Pink", value: "rgba(244, 114, 182, 0.35)" },
  { label: "Red", value: "rgba(248, 113, 113, 0.35)" },
];

const SLASH_COMMANDS = [
  { id: "text", label: "Text", shortcut: "P", group: "block" },
  { id: "h1", label: "Heading 1", shortcut: "H1", group: "block" },
  { id: "h2", label: "Heading 2", shortcut: "H2", group: "block" },
  { id: "h3", label: "Heading 3", shortcut: "H3", group: "block" },
  { id: "bullet", label: "Bulleted list", shortcut: "*", group: "block" },
  { id: "numbered", label: "Numbered list", shortcut: "1.", group: "block" },
  { id: "todo", label: "Todo", shortcut: "[]", group: "block" },
  { id: "quote", label: "Quote", shortcut: ">", group: "block" },
  { id: "callout", label: "Callout", shortcut: "!", group: "block" },
  { id: "important", label: "Important", shortcut: "!!", group: "block", projectOnly: true },
  { id: "toggle", label: "Toggle", shortcut: ">v", group: "block" },
  { id: "table", label: "Table", shortcut: "3x3", group: "block" },
  { id: "code", label: "Code block", shortcut: "```", group: "block" },
  { id: "divider", label: "Divider", shortcut: "---", group: "block" },
  { id: "bold", label: "Bold", shortcut: "B", group: "inline" },
  { id: "italic", label: "Italic", shortcut: "I", group: "inline" },
  { id: "underline", label: "Underline", shortcut: "U", group: "inline" },
  { id: "link", label: "Link", shortcut: "->", group: "inline" },
  { id: "color", label: "Text color", shortcut: "A", group: "inline" },
  { id: "highlight", label: "Highlight", shortcut: "==", group: "inline" },
  { id: "image", label: "Image", shortcut: "Img", group: "media" },
  { id: "excel", label: "Excel workbook", shortcut: "XLSX", group: "media" },
  { id: "email", label: "Email", shortcut: "@", group: "media" },
  { id: "file", label: "File link", shortcut: "FILE", group: "media" },
  { id: "page", label: "Page", shortcut: "+", group: "page", projectOnly: true },
  { id: "canvaspage", label: "Canvas page", shortcut: "<>", group: "page", projectOnly: true },
  { id: "pageref", label: "Link to page", shortcut: "[[", group: "page" },
];

function commandMatches(command, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  return command.label.toLowerCase().includes(q) || command.id.includes(q);
}

function NotesSidebar({ context, editor = null }) {
  const globalPages = Array.isArray(context.globalPages) ? context.globalPages : [];
  return (
      <aside className="notes-sidebar" aria-label="Notes navigation">
        <div className="notes-project-summary">
          <span className="notes-eyebrow">ACIES / {context.kind === "global" ? "Workspace" : "Project"}</span>
          <strong>{context.project?.name || context.title || "Untitled"}</strong>
        </div>
        <nav className="notes-page-nav" aria-label="Pages">
          <div className="page-child-links-label">Notes</div>
          {context.kind !== "global" ? <>
            <button type="button" className={`notes-nav-link ${context.kind === "project" ? "is-active" : ""}`}
              aria-current={context.kind === "project" ? "page" : undefined}
              onClick={() => context.onOpenOverview?.()}>
              <span aria-hidden="true">▤</span> Overview
            </button>
            {(context.navigationPages || context.childPages || []).map((child) => (
              <div className={`notes-nav-row ${context.subpage?.id === child.id ? "is-active" : ""}`} key={child.id}>
                <button type="button" className="notes-nav-link"
                  style={{ paddingLeft: `${12 + Math.min(child.depth || 0, 5) * 14}px` }}
                  aria-current={context.subpage?.id === child.id ? "page" : undefined}
                  title={child.title} onClick={() => context.onOpenSubpage?.(child.id)}>
                  <span aria-hidden="true">{child.canvas ? "◇" : "▤"}</span>
                  <span className="notes-nav-title">{child.title || "Untitled"}</span>
                </button>
                <button type="button" className="notes-nav-delete" aria-label={`Delete ${child.title || "Untitled"}`}
                  title="Delete subpage" onClick={() => context.onDeleteSubpage?.(child.id)}>×</button>
              </div>
            ))}
            <button type="button" className="notes-nav-link notes-nav-add" onClick={() => context.onCreateSubpage?.()}>
              <span aria-hidden="true">+</span> Add subpage
            </button>
            <button type="button" className="notes-nav-link notes-nav-add" onClick={() => context.onCreateSubpage?.("canvas")}>
              <span aria-hidden="true">+</span> Add canvas
            </button>
          </> : globalPages.map((page) => (
            <button type="button" key={page.id}
              className={`notes-nav-link ${context.globalPage?.id === page.id ? "is-active" : ""}`}
              aria-current={context.globalPage?.id === page.id ? "page" : undefined}
              onClick={() => context.onOpenGlobalPage?.(page.id)}>
              <span aria-hidden="true">▤</span><span className="notes-nav-title">{page.title || "Untitled"}</span>
            </button>
          ))}
        </nav>
        <NotesOutline editor={editor} documentKey={context.documentKey} />
      </aside>
  );
}

function PageEditorApp() {
  const [context, setContext] = useState(currentContext);

  useEffect(() => subscribe(setContext), []);

  if (!context) return null;
  if (context.navigationOnly) {
    const sidebar = document.getElementById("pageCanvasSidebarRoot");
    return sidebar ? createPortal(<NotesSidebar context={context} />, sidebar) : null;
  }
  return <PageEditor context={context} options={currentOptions} />;
}

function NotesOutline({ editor, documentKey }) {
  const [headings, setHeadings] = useState([]);
  useEffect(() => {
    if (!editor) return;
    const refresh = () => {
      setHeadings(Array.from(editor.view.dom.querySelectorAll("h1, h2, h3"))
        .filter((node) => node.textContent.trim())
        .map((node) => ({ node, title: node.textContent, level: node.tagName })));
    };
    const frame = requestAnimationFrame(refresh);
    editor.on("update", refresh);
    return () => {
      cancelAnimationFrame(frame);
      editor.off("update", refresh);
    };
  }, [editor, documentKey]);
  if (!headings.length) return null;
  return <nav className="notes-outline" aria-label="On this page">
    <div className="page-child-links-label">On this page</div>
    {headings.map(({ node, title, level }, index) => (
      <button type="button" key={index} className={`notes-outline-link ${level.toLowerCase()}`}
        onClick={() => node.scrollIntoView({ block: "center", behavior: "smooth" })}>
        {title}
      </button>
    ))}
  </nav>;
}

function PageEditor({ context, options }) {
  const fileInputRef = useRef(null);
  const workbookInputRef = useRef(null);
  const titleElementRef = useRef(null);
  const titleValueRef = useRef(context.title || "");
  const hydrateWorkbooksRef = useRef(async () => {});
  const workbookHydrationFrameRef = useRef(null);
  const saveTimerRef = useRef(null);
  const titleTimerRef = useRef(null);
  const suppressUpdateRef = useRef(false);
  const [slash, setSlash] = useState({ open: false, query: "", selected: 0, range: null, pos: null });
  const [pageLink, setPageLink] = useState({ open: false, query: "", selected: 0, range: null, pos: null });
  const [colorMenu, setColorMenu] = useState({ open: false, mode: "color", pos: null });
  const [calloutMenu, setCalloutMenu] = useState({ open: false, pos: null });
  const [tableMenu, setTableMenu] = useState({ open: false, pos: null });
  const [codeMenu, setCodeMenu] = useState({ open: false, pos: null, language: "" });
  const [workbookDialog, setWorkbookDialog] = useState(createWorkbookDialogState);

  const globalPages = Array.isArray(context.globalPages) ? context.globalPages : [];
  const pageLinkMatches = useMemo(() => {
    const q = String(pageLink.query || "").trim().toLowerCase();
    const matched = globalPages
      .filter((page) => !q || String(page.title || "").toLowerCase().includes(q))
      .slice(0, 8)
      .map((page) => ({ type: "page", page }));
    const exact = globalPages.some((page) => String(page.title || "").trim().toLowerCase() === q);
    if (q && !exact) matched.push({ type: "create", title: pageLink.query.trim() });
    return matched;
  }, [globalPages, pageLink.query]);

  const visibleSlashCommands = useMemo(
    () =>
      SLASH_COMMANDS.filter((command) => {
        if (command.projectOnly && context.kind === "global") return false;
        return commandMatches(command, slash.query);
      }),
    [context.kind, slash.query]
  );

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        link: false,
        underline: false,
        codeBlock: false,
      }),
      CodeBlockLowlight.configure({ lowlight, defaultLanguage: null }),
      Underline,
      TextStyle,
      Color,
      Link.configure({
        autolink: true,
        openOnClick: false,
        HTMLAttributes: { target: "_blank", rel: "noopener noreferrer" },
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Highlight.configure({ multicolor: true }),
      TableKit.configure({ table: { resizable: false } }),
      Details.configure({ persist: true, HTMLAttributes: { class: "page-toggle" } }),
      DetailsSummary,
      DetailsContent,
      PageCallout,
      PageImportant,
      PageImage,
      PageLink,
      PageWorkbook,
      PageEmail,
      PageAttachment,
    ],
    content: context.html || "",
    editorProps: {
      attributes: {
        id: "pageEditor",
        class: "page-editor project-pages-editor-content",
        spellcheck: "true",
        role: "textbox",
        "aria-multiline": "true",
        "aria-label": "Page content",
        "data-placeholder": "Type here - add headings, images, links, and notes...",
      },
      handleKeyDown(view, event) {
        if (colorMenu.open && event.key === "Escape") {
          event.preventDefault();
          setColorMenu((state) => ({ ...state, open: false }));
          return true;
        }
        if (pageLink.open) {
          if (event.key === "Escape") {
            event.preventDefault();
            setPageLink((state) => ({ ...state, open: false }));
            return true;
          }
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setPageLink((state) => ({
              ...state,
              selected:
                (state.selected + (event.key === "ArrowDown" ? 1 : -1) + pageLinkMatches.length) %
                Math.max(pageLinkMatches.length, 1),
            }));
            return true;
          }
          if (event.key === "Enter" || event.key === "Tab") {
            event.preventDefault();
            choosePageLinkMatch(pageLinkMatches[pageLink.selected] || pageLinkMatches[0]);
            return true;
          }
        }
        if (slash.open) {
          if (event.key === "Escape") {
            event.preventDefault();
            setSlash((state) => ({ ...state, open: false }));
            return true;
          }
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setSlash((state) => ({
              ...state,
              selected:
                (state.selected + (event.key === "ArrowDown" ? 1 : -1) + visibleSlashCommands.length) %
                Math.max(visibleSlashCommands.length, 1),
            }));
            return true;
          }
          if (event.key === "Enter" || event.key === "Tab") {
            event.preventDefault();
            executeSlashCommand(visibleSlashCommands[slash.selected] || visibleSlashCommands[0]);
            return true;
          }
        }
        if (selectionWouldDeleteWorkbook(view.state, event.key)) {
          event.preventDefault();
          context.onToast?.("Use the workbook card's Delete or Remove link button.");
          return true;
        }
        if (event.key === "Tab" && !event.ctrlKey && !event.metaKey && !event.altKey) {
          if (editor?.isActive("table")) {
            event.preventDefault();
            if (event.shiftKey) editor.chain().focus().goToPreviousCell().run();
            else editor.chain().focus().goToNextCell().run();
            return true;
          }
          if (editor?.isActive("codeBlock")) {
            if (event.shiftKey) return false;
            event.preventDefault();
            editor.chain().focus().insertContent("  ").run();
            return true;
          }
          const chain = editor?.chain().focus();
          if (chain) {
            event.preventDefault();
            if (event.shiftKey) chain.liftListItem("listItem").run();
            else chain.sinkListItem("listItem").run();
            return true;
          }
        }
        return false;
      },
      handlePaste(view, event) {
        const files = Array.from(event.clipboardData?.files || []).filter((file) =>
          String(file.type || "").toLowerCase().startsWith("image/")
        );
        if (!files.length) return false;
        event.preventDefault();
        void insertImageFiles(files);
        return true;
      },
      transformPastedHTML(html) {
        const document = new DOMParser().parseFromString(html, "text/html");
        // Keep intentional formatting when copying between notes. External HTML
        // often pairs dark text with a light email background that we don't keep.
        if (document.querySelector("[data-pm-slice]")) return html;
        document.querySelectorAll("[style], [color], [bgcolor]").forEach((element) => {
          element.style.removeProperty("color");
          element.style.removeProperty("background");
          element.style.removeProperty("background-color");
          element.style.removeProperty("-webkit-text-fill-color");
          element.removeAttribute("color");
          element.removeAttribute("bgcolor");
        });
        return document.body.innerHTML;
      },
      handleDrop(view, event) {
        const files = Array.from(event.dataTransfer?.files || []).filter((file) =>
          String(file.type || "").toLowerCase().startsWith("image/")
        );
        if (files.length) {
          event.preventDefault();
          clearEmailDropTarget(view);
          void insertImageFiles(files);
          return true;
        }
        if (!context.onAttachEmailDrop || !looksLikeExternalEmailDrop(event.dataTransfer)) {
          clearEmailDropTarget(view);
          return false;
        }
        const coords = view.posAtCoords({ left: event.clientX, top: event.clientY });
        event.preventDefault();
        clearEmailDropTarget(view);
        // The DataTransfer is dead the moment this handler returns, so the host has to
        // read it now. onAttachEmailDrop captures synchronously and resolves afterwards.
        void attachDroppedEmail(context.onAttachEmailDrop(event), coords ? coords.pos : null);
        return true;
      },
      handleDOMEvents: {
        dragover(view, event) {
          if (!context.onAttachEmailDrop || !looksLikeExternalEmailDrop(event.dataTransfer)) {
            return false;
          }
          event.preventDefault();
          if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
          const coords = view.posAtCoords({ left: event.clientX, top: event.clientY });
          setEmailDropTarget(view, coords ? coords.pos : null);
          return false;
        },
        dragleave(view, event) {
          if (event.relatedTarget && view.dom.contains(event.relatedTarget)) return false;
          clearEmailDropTarget(view);
          return false;
        },
      },
    },
    onUpdate({ editor: activeEditor }) {
      if (suppressUpdateRef.current) return;
      queueHtmlSave(activeEditor.getHTML());
      refreshMenus(activeEditor);
      scheduleWorkbookHydration();
    },
    onSelectionUpdate({ editor: activeEditor }) {
      refreshMenus(activeEditor);
    },
  });

  const hydrateImages = useCallback(async () => {
    if (!editor || !context.onGetAsset) return;
    const imgs = Array.from(editor.view.dom.querySelectorAll("img[data-asset]"));
    for (const img of imgs) {
      if (img.getAttribute("src")) continue;
      try {
        const result = await context.onGetAsset(img.getAttribute("data-asset"));
        if (result?.status === "success" && result.dataUrl) {
          img.src = result.dataUrl;
        } else {
          img.alt = "Image unavailable";
          img.classList.add("page-image-missing");
        }
      } catch (error) {
        console.warn("Page image hydrate failed:", error);
      }
    }
  }, [context, editor]);

  const hydrateWorkbooks = useCallback(async () => {
    if (!editor || !context.onGetPageFileInfo) return;
    const cards = Array.from(editor.view.dom.querySelectorAll(".page-workbook[data-page-file]"));
    for (const card of cards) {
      if (card.dataset.workbookHydrated === "true" || card.dataset.workbookHydrated === "pending") {
        continue;
      }
      card.dataset.workbookHydrated = "pending";
      const fileRef = card.getAttribute("data-page-file") || "";
      const declaredStorageType = card.getAttribute("data-file-storage") || "managed";
      const status = card.querySelector(".page-workbook-status");
      const openButton = card.querySelector('[data-workbook-action="open"]');
      const deleteButton = card.querySelector('[data-workbook-action="delete"]');
      try {
        const result = await context.onGetPageFileInfo(fileRef);
        const available = result?.status === "success" && result.exists === true;
        const storageType = result?.storageType || declaredStorageType;
        card.classList.toggle("is-unavailable", !available);
        if (status) {
          status.textContent = available
            ? storageType === "external"
              ? "Linked to existing file"
              : "Stored locally"
            : "Unavailable on this device";
        }
        if (openButton) openButton.disabled = !available;
        if (deleteButton) deleteButton.textContent = storageType === "external" ? "Remove link" : "Delete";
      } catch (error) {
        card.classList.add("is-unavailable");
        if (status) status.textContent = "Unavailable on this device";
        if (openButton) openButton.disabled = true;
        console.warn("Page workbook hydrate failed:", error);
      } finally {
        card.dataset.workbookHydrated = "true";
      }
    }
  }, [context, editor]);
  hydrateWorkbooksRef.current = hydrateWorkbooks;

  const flushSave = useCallback(async () => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    if (titleTimerRef.current) {
      clearTimeout(titleTimerRef.current);
      titleTimerRef.current = null;
      context.onTitleChange?.(titleValueRef.current);
    }
    if (editor) {
      await context.onHtmlChange?.(stripTransientPageHtml(editor.getHTML()), { immediate: true });
    }
  }, [context, editor]);

  useEffect(() => {
    flushCurrentEditor = flushSave;
    return () => {
      if (flushCurrentEditor === flushSave) flushCurrentEditor = null;
    };
  }, [flushSave]);

  useEffect(() => {
    if (!editor) return;
    suppressUpdateRef.current = true;
    editor.commands.setContent(context.html || "", false);
    suppressUpdateRef.current = false;
    titleValueRef.current = context.title || "";
    if (titleElementRef.current) {
      titleElementRef.current.textContent = titleValueRef.current;
    }
    setSlash({ open: false, query: "", selected: 0, range: null, pos: null });
    setPageLink({ open: false, query: "", selected: 0, range: null, pos: null });
    setWorkbookDialog(createWorkbookDialogState());
    const frame = requestAnimationFrame(() => {
      if (editor.isDestroyed) return;
      void hydrateImages();
      void hydrateWorkbooks();
      if (context.focusImportant) {
        const target = editor.view.dom.querySelector('[data-important="true"]');
        if (target) {
          // Bail before focus("end"), which would scroll straight back to the bottom.
          target.scrollIntoView({ block: "center", behavior: "auto" });
          target.classList.add("is-important-focused");
          setTimeout(() => target.classList.remove("is-important-focused"), 1600);
          return;
        }
      }
      editor.commands.focus("end");
    });
    return () => cancelAnimationFrame(frame);
  }, [context.documentKey, editor]);

  useEffect(() => {
    void hydrateImages();
  }, [context.documentKey, hydrateImages]);

  useEffect(() => {
    void hydrateWorkbooks();
  }, [context.documentKey, hydrateWorkbooks]);

  useEffect(() => {
    if (!workbookDialog.open) return;
    requestAnimationFrame(() => {
      workbookInputRef.current?.focus();
      workbookInputRef.current?.select();
    });
  }, [workbookDialog.open, workbookDialog.mode]);

  useEffect(
    () => () => {
      if (workbookHydrationFrameRef.current !== null) {
        cancelAnimationFrame(workbookHydrationFrameRef.current);
      }
    },
    []
  );

  function scheduleWorkbookHydration() {
    if (workbookHydrationFrameRef.current !== null) return;
    workbookHydrationFrameRef.current = requestAnimationFrame(() => {
      workbookHydrationFrameRef.current = null;
      void hydrateWorkbooksRef.current();
    });
  }

  function queueHtmlSave(html) {
    context.onHtmlChange?.(stripTransientPageHtml(html), { immediate: false });
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null;
      context.onRequestPersist?.();
    }, 700);
  }

  function refreshMenus(activeEditor) {
    const slashQuery = detectSlashQuery(activeEditor);
    if (slashQuery) {
      setSlash((state) => ({
        open: true,
        query: slashQuery.query,
        range: slashQuery.range,
        pos: slashQuery.pos,
        selected: Math.min(state.selected || 0, Math.max(visibleSlashCommands.length - 1, 0)),
      }));
    } else {
      setSlash((state) => (state.open ? { ...state, open: false } : state));
    }

    setColorMenu((state) => (state.open ? { ...state, open: false } : state));

    if (activeEditor.isActive("pageCallout")) {
      const rect = getActiveBlockRect(activeEditor, ".page-callout");
      setCalloutMenu({ open: true, pos: rect ? { left: rect.left, top: rect.top } : null });
    } else {
      setCalloutMenu((state) => (state.open ? { ...state, open: false } : state));
    }

    if (activeEditor.isActive("table")) {
      const rect = getActiveBlockRect(activeEditor, "table");
      setTableMenu({ open: true, pos: rect ? { left: rect.left, top: rect.top } : null });
    } else {
      setTableMenu((state) => (state.open ? { ...state, open: false } : state));
    }

    if (activeEditor.isActive("codeBlock")) {
      const rect = getActiveBlockRect(activeEditor, "pre");
      setCodeMenu({
        open: true,
        pos: rect ? { left: rect.left, top: rect.top } : null,
        language: activeEditor.getAttributes("codeBlock").language || "",
      });
    } else {
      setCodeMenu((state) => (state.open ? { ...state, open: false } : state));
    }

    const pageQuery = detectPageLinkQuery(activeEditor);
    if (pageQuery) {
      setPageLink((state) => ({
        open: true,
        query: pageQuery.query,
        range: pageQuery.range,
        pos: pageQuery.pos,
        selected: Math.min(state.selected || 0, Math.max(pageLinkMatches.length - 1, 0)),
      }));
    } else {
      setPageLink((state) => (state.open ? { ...state, open: false } : state));
    }
  }

  function deleteRange(range) {
    if (!editor || !range) return editor?.chain().focus();
    return editor.chain().focus().deleteRange(range);
  }

  function executeSlashCommand(command) {
    if (!editor || !command) return;
    let chain = deleteRange(slash.range);
    if (command.id === "text") chain.setParagraph().run();
    else if (command.id === "h1") chain.toggleHeading({ level: 1 }).run();
    else if (command.id === "h2") chain.toggleHeading({ level: 2 }).run();
    else if (command.id === "h3") chain.toggleHeading({ level: 3 }).run();
    else if (command.id === "bullet") chain.toggleBulletList().run();
    else if (command.id === "numbered") chain.toggleOrderedList().run();
    else if (command.id === "todo") chain.toggleTaskList().run();
    else if (command.id === "quote") chain.toggleBlockquote().run();
    else if (command.id === "callout") chain.setCallout().run();
    else if (command.id === "important") chain.toggleImportant().run();
    else if (command.id === "toggle") chain.setDetails().run();
    else if (command.id === "table") chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
    else if (command.id === "code") chain.toggleCodeBlock().run();
    else if (command.id === "divider") chain.setHorizontalRule().run();
    else if (command.id === "bold") chain.toggleBold().run();
    else if (command.id === "italic") chain.toggleItalic().run();
    else if (command.id === "underline") chain.toggleUnderline().run();
    else if (command.id === "color" || command.id === "highlight") {
      const pos = slash.pos;
      chain.run();
      requestAnimationFrame(() =>
        setColorMenu({ open: true, mode: command.id === "highlight" ? "highlight" : "color", pos })
      );
    }
    else if (command.id === "link") {
      chain.run();
      const url = window.prompt("Link URL", "https://");
      if (url && url.trim() && url.trim() !== "https://") {
        editor.chain().focus().extendMarkRange("link").setLink({ href: normalizeHref(url) }).run();
      }
    } else if (command.id === "image") {
      chain.run();
      fileInputRef.current?.click();
    } else if (command.id === "excel") {
      chain.run();
      setWorkbookDialog({ ...createWorkbookDialogState(), open: true });
    } else if (command.id === "email") {
      chain.run();
      void attachEmailFromPicker();
    } else if (command.id === "file") {
      chain.run();
      const pos = editor.state.selection.from;
      void context.onPickAttachment?.().then((attachments) => {
        if (!attachments?.length || editor.isDestroyed) return;
        editor.chain().focus().insertContentAt(Math.min(pos, editor.state.doc.content.size),
          attachments.flatMap((attrs) => [{ type: "pageAttachment", attrs }, { type: "text", text: " " }])).run();
      }).catch((error) => context.onToast?.(error?.message || "Could not add file link."));
    } else if (command.id === "page") {
      chain.run();
      context.onCreateSubpage?.();
    } else if (command.id === "canvaspage") {
      chain.run();
      context.onCreateSubpage?.("canvas");
    } else if (command.id === "pageref") {
      chain.insertContent("[[").run();
    }
    setSlash((state) => ({ ...state, open: false }));
  }

  function applyColorChoice(value) {
    if (!editor) return;
    const chain = editor.chain().focus();
    if (colorMenu.mode === "highlight") {
      if (value) chain.setHighlight({ color: value }).run();
      else chain.unsetHighlight().run();
    } else {
      if (value) chain.setColor(value).run();
      else chain.unsetColor().run();
    }
    setColorMenu((state) => ({ ...state, open: false }));
  }

  function choosePageLinkMatch(match) {
    if (!editor || !match) return;
    let page = match.page;
    if (match.type === "create") {
      page = context.onCreateGlobalPage?.(match.title);
    }
    if (!page) return;
    deleteRange(pageLink.range)
      .insertPageLink({ pageId: page.id, title: page.title || "Untitled" })
      .run();
    setPageLink((state) => ({ ...state, open: false }));
  }

  async function insertImageFiles(files) {
    if (!editor || !context.onSaveAsset) return;
    for (const file of Array.from(files || [])) {
      if (!String(file.type || "").toLowerCase().startsWith("image/")) continue;
      try {
        const dataUrl = await readFileAsDataUrl(file);
        const result = await context.onSaveAsset(dataUrl, file.name || "");
        if (result?.status !== "success" || !result.assetPath) {
          context.onToast?.(result?.message || "Could not save image.");
          continue;
        }
        editor
          .chain()
          .focus()
          .setImage({
            src: dataUrl,
            assetPath: result.assetPath,
            alt: file.name || "Image",
            widthPercent: "80",
            class: "page-inline-image",
            style: "max-width: 100%;",
          })
          .run();
      } catch (error) {
        console.warn("Page image insert failed:", error);
      }
    }
  }

  function insertPageEmailAtPos(emailRef, pos) {
    if (!editor || !emailRef) return;
    const attrs = {};
    PAGE_EMAIL_ATTRS.forEach(([key]) => {
      attrs[key] = String(emailRef[key] || "");
    });
    if (!attrs.raw && !attrs.url) return;
    if (!attrs.label) attrs.label = "Email";

    const doc = editor.state.doc;
    let insertAt = doc.content.size;
    if (Number.isInteger(pos) && pos >= 0 && pos <= doc.content.size) {
      const $pos = doc.resolve(pos);
      let depth = $pos.depth;
      while (depth > 0 && !$pos.node(depth).isTextblock) depth -= 1;
      // Append to the end of the hovered line: dropping "on" a line should never
      // split a word at the pointer.
      insertAt = depth > 0 ? $pos.end(depth) : pos;
    }
    editor.chain().focus().insertContentAt(insertAt, { type: "pageEmail", attrs }).run();
  }

  async function resolveAndInsertEmail(pending, pos) {
    let result = null;
    try {
      result = await pending;
    } catch (error) {
      context.onToast?.(error?.message || "Could not attach the email.");
      return;
    }
    if (!result || result.status !== "success" || !result.emailRef) {
      if (result?.message) context.onToast?.(result.message);
      return;
    }
    insertPageEmailAtPos(result.emailRef, pos);
  }

  function attachDroppedEmail(pending, pos) {
    return resolveAndInsertEmail(pending, pos);
  }

  function attachEmailFromPicker() {
    if (!context.onPickEmail) {
      context.onToast?.("Email attaching is unavailable.");
      return Promise.resolve();
    }
    const pos = editor?.state.selection.$from.pos ?? null;
    return resolveAndInsertEmail(context.onPickEmail(), pos);
  }

  function closeWorkbookDialog() {
    if (workbookDialog.creating || workbookDialog.browsing) return;
    setWorkbookDialog(createWorkbookDialogState());
    requestAnimationFrame(() => editor?.commands.focus());
  }

  async function submitWorkbookDialog() {
    const isExternal = workbookDialog.mode === "link";
    const name = String(workbookDialog.name || "").trim();
    const path = String(workbookDialog.path || "").trim();
    if (!isExternal && !name) {
      setWorkbookDialog((state) => ({ ...state, error: "Workbook name is required." }));
      return;
    }
    if (isExternal && !path) {
      setWorkbookDialog((state) => ({ ...state, error: "Workbook path is required." }));
      return;
    }
    const submit = isExternal ? context.onLinkWorkbook : context.onCreateWorkbook;
    if (!submit) {
      setWorkbookDialog((state) => ({
        ...state,
        error: isExternal ? "Workbook linking is unavailable." : "Workbook creation is unavailable.",
      }));
      return;
    }

    setWorkbookDialog((state) => ({ ...state, creating: true, error: "" }));
    try {
      const result = await submit(isExternal ? path : name);
      if (result?.status !== "success" || !result.fileRef) {
        setWorkbookDialog((state) => ({
          ...state,
          creating: false,
          error: result?.message || (isExternal ? "Could not link workbook." : "Could not create workbook."),
        }));
        return;
      }
      editor
        ?.chain()
        .focus()
        .insertPageWorkbook({
          fileRef: result.fileRef,
          fileName: result.fileName || `${name.replace(/\.xlsx$/i, "")}.xlsx`,
          storageType: result.storageType || (isExternal ? "external" : "managed"),
        })
        .run();
      setWorkbookDialog(createWorkbookDialogState());
      requestAnimationFrame(() => void hydrateWorkbooks());
    } catch (error) {
      setWorkbookDialog((state) => ({
        ...state,
        creating: false,
        error: error?.message || (isExternal ? "Could not link workbook." : "Could not create workbook."),
      }));
    }
  }

  async function chooseExistingWorkbook() {
    if (!context.onChooseWorkbookFile) {
      setWorkbookDialog((state) => ({ ...state, error: "File picker is unavailable." }));
      return;
    }
    setWorkbookDialog((state) => ({ ...state, browsing: true, error: "" }));
    try {
      const result = await context.onChooseWorkbookFile();
      if (result?.status === "success" && Array.isArray(result.paths) && result.paths[0]) {
        setWorkbookDialog((state) => ({
          ...state,
          mode: "link",
          path: result.paths[0],
          browsing: false,
          error: "",
        }));
      } else {
        setWorkbookDialog((state) => ({
          ...state,
          browsing: false,
          error: result?.status === "error" ? result?.message || "Could not choose workbook." : "",
        }));
      }
    } catch (error) {
      setWorkbookDialog((state) => ({
        ...state,
        browsing: false,
        error: error?.message || "Could not choose workbook.",
      }));
    }
  }

  function handleTitleInput(event) {
    const value = event.currentTarget.textContent || "";
    // The browser owns the children of this contentEditable element while the
    // user types. Keep the current value in a ref so React never reconciles
    // those text nodes and cannot retain a stale insertBefore reference.
    titleValueRef.current = value;
    if (titleTimerRef.current) clearTimeout(titleTimerRef.current);
    titleTimerRef.current = setTimeout(() => {
      titleTimerRef.current = null;
      context.onTitleChange?.(value);
    }, 500);
  }

  async function handleEditorClick(event) {
    const emailAction = event.target.closest?.("[data-email-action]");
    if (emailAction) {
      event.preventDefault();
      event.stopPropagation();
      const chip = emailAction.closest(".page-email[data-email-raw]");
      if (!chip) return;
      const attrs = readPageEmailAttrs(chip);
      const label = attrs.label || "this email";

      if (emailAction.dataset.emailAction === "open") {
        try {
          const result = await context.onOpenEmail?.(attrs);
          if (result && result.status && result.status !== "success") {
            chip.classList.add("is-unavailable");
            context.onToast?.(result.message || "Could not open the email.");
          } else {
            chip.classList.remove("is-unavailable");
          }
        } catch (error) {
          chip.classList.add("is-unavailable");
          context.onToast?.(error?.message || "Could not open the email.");
        }
        return;
      }

      if (emailAction.dataset.emailAction === "remove") {
        const managed = attrs.source === "saved-file";
        const confirmation = managed
          ? `Remove "${label}"?\n\nThe saved copy of the message will be deleted.`
          : `Remove "${label}"?`;
        if (!window.confirm(confirmation)) return;
        emailAction.disabled = true;
        try {
          const result = await context.onDeleteEmail?.(attrs);
          if (result && result.status && result.status !== "success") {
            context.onToast?.(result.message || "Could not remove the email.");
            emailAction.disabled = false;
            return;
          }
          let emailPos = null;
          let emailNode = null;
          editor?.state.doc.descendants((node, pos) => {
            if (emailNode) return false;
            if (node.type.name === "pageEmail" && node.attrs.raw === attrs.raw) {
              emailPos = pos;
              emailNode = node;
              return false;
            }
            return true;
          });
          if (Number.isInteger(emailPos) && emailNode) {
            editor.view.dispatch(
              editor.state.tr
                .delete(emailPos, emailPos + emailNode.nodeSize)
                // Undo must not resurrect a chip whose saved .msg is already gone.
                .setMeta("addToHistory", false)
            );
            editor.commands.focus();
          }
        } catch (error) {
          context.onToast?.(error?.message || "Could not remove the email.");
          emailAction.disabled = false;
        }
        return;
      }
    }

    const workbookAction = event.target.closest?.("[data-workbook-action]");
    if (workbookAction) {
      event.preventDefault();
      event.stopPropagation();
      const card = workbookAction.closest(".page-workbook[data-page-file]");
      const fileRef = card?.getAttribute("data-page-file") || "";
      const fileName = card?.getAttribute("data-file-name") || "Workbook.xlsx";
      const external =
        card?.getAttribute("data-file-storage") === "external" || fileRef.startsWith("page_file_links/");
      if (!card || !fileRef) return;

      if (workbookAction.dataset.workbookAction === "open") {
        workbookAction.disabled = true;
        try {
          const result = await context.onOpenPageFile?.(fileRef);
          if (result?.status !== "success") {
            context.onToast?.(result?.message || "Could not open workbook.");
            delete card.dataset.workbookHydrated;
            void hydrateWorkbooks();
          }
        } catch (error) {
          context.onToast?.(error?.message || "Could not open workbook.");
          delete card.dataset.workbookHydrated;
          void hydrateWorkbooks();
        } finally {
          if (!card.classList.contains("is-unavailable")) workbookAction.disabled = false;
        }
        return;
      }

      if (workbookAction.dataset.workbookAction === "delete") {
        const confirmation = external
          ? `Remove the link to "${fileName}"?\n\nThe original file will not be deleted.`
          : `Permanently delete "${fileName}"?`;
        if (!window.confirm(confirmation)) return;
        workbookAction.disabled = true;
        try {
          const result = await context.onDeletePageFile?.(fileRef);
          if (result?.status !== "success") {
            context.onToast?.(result?.message || "Could not delete workbook.");
            workbookAction.disabled = false;
            return;
          }
          let workbookPos = null;
          let workbookNode = null;
          editor?.state.doc.descendants((node, pos) => {
            if (node.type.name === "pageWorkbook" && node.attrs.fileRef === fileRef) {
              workbookPos = pos;
              workbookNode = node;
              return false;
            }
            return true;
          });
          if (Number.isInteger(workbookPos) && workbookNode) {
            editor.view.dispatch(
              editor.state.tr
                .delete(workbookPos, workbookPos + workbookNode.nodeSize)
                .setMeta("addToHistory", false)
            );
            editor.commands.focus();
          }
          context.onToast?.(external ? `Removed link to ${fileName}.` : `Deleted ${fileName}.`);
        } catch (error) {
          context.onToast?.(error?.message || "Could not delete workbook.");
          workbookAction.disabled = false;
        }
        return;
      }
    }

    const pageAnchor = event.target.closest?.("a.page-wiki-link[data-page-id]");
    if (pageAnchor) {
      event.preventDefault();
      context.onOpenGlobalPage?.(pageAnchor.getAttribute("data-page-id"));
      return;
    }
    const attachment = event.target.closest?.(".page-attachment[data-attachment-target]");
    if (attachment) {
      event.preventDefault();
      context.onOpenAttachment?.({
        type: attachment.getAttribute("data-attachment-type"),
        target: attachment.getAttribute("data-attachment-target"),
        description: attachment.textContent,
      });
      return;
    }
    const link = event.target.closest?.("a[href]");
    if (link && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      window.open(link.href, "_blank", "noopener,noreferrer");
    }
  }

  return (
    <div className="project-pages-editor" onClick={handleEditorClick} onKeyDown={(event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target.matches?.(".page-attachment")) handleEditorClick(event);
    }}>
      <NotesSidebar context={context} editor={editor} />
      <div className="notes-document">
      <div className="notes-eyebrow">{context.kind === "global" ? "Workspace notes" : "Project notes"}</div>
      <h1
        ref={titleElementRef}
        id="pageTitle"
        className="page-title project-pages-title"
        contentEditable
        suppressContentEditableWarning
        spellCheck
        role="textbox"
        aria-label="Page title"
        data-placeholder="Untitled"
        onInput={handleTitleInput}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            editor?.commands.focus();
          }
        }}
      />

      <div className="project-pages-editor-surface">
        <EditorContent editor={editor} />
      </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(event) => {
          void insertImageFiles(event.currentTarget.files || []);
          event.currentTarget.value = "";
        }}
      />

      <WorkbookDialog
        open={workbookDialog.open}
        mode={workbookDialog.mode}
        name={workbookDialog.name}
        path={workbookDialog.path}
        error={workbookDialog.error}
        creating={workbookDialog.creating}
        browsing={workbookDialog.browsing}
        inputRef={workbookInputRef}
        onMode={(mode) => setWorkbookDialog((state) => ({ ...state, mode, error: "" }))}
        onName={(name) =>
          setWorkbookDialog((state) => ({ ...state, name, error: "" }))
        }
        onPath={(path) => setWorkbookDialog((state) => ({ ...state, path, error: "" }))}
        onBrowse={chooseExistingWorkbook}
        onCancel={closeWorkbookDialog}
        onSubmit={submitWorkbookDialog}
      />

      <CommandMenu
        id="pageSlashMenu"
        open={slash.open}
        position={slash.pos}
        header={slash.query ? `/${slash.query}` : "Type a command"}
        rows={visibleSlashCommands.map((command) => ({
          key: command.id,
          label: command.label,
          shortcut: command.shortcut,
          selected: visibleSlashCommands[slash.selected]?.id === command.id,
          onMouseDown: () => executeSlashCommand(command),
        }))}
      />
      <CodeMenu
        open={codeMenu.open}
        position={codeMenu.pos}
        language={codeMenu.language}
        onLanguage={(language) =>
          editor?.chain().focus().updateAttributes("codeBlock", { language: language || null }).run()
        }
      />
      <TableMenu
        open={tableMenu.open}
        position={tableMenu.pos}
        editor={editor}
      />
      <CalloutMenu
        open={calloutMenu.open}
        position={calloutMenu.pos}
        onEmoji={(emoji) => editor?.chain().focus().updateCalloutAttrs({ emoji }).run()}
        onColor={(color) => editor?.chain().focus().updateCalloutAttrs({ color }).run()}
      />
      <ColorMenu
        open={colorMenu.open}
        mode={colorMenu.mode}
        position={colorMenu.pos}
        colors={colorMenu.mode === "highlight" ? HIGHLIGHT_COLORS : TEXT_COLORS}
        onPick={applyColorChoice}
      />
      <CommandMenu
        id="pageLinkMenu"
        open={pageLink.open}
        position={pageLink.pos}
        header={pageLink.query ? `[[${pageLink.query}` : "Link to page"}
        rows={pageLinkMatches.map((match, index) => ({
          key: match.type === "create" ? `create:${match.title}` : match.page.id,
          label: match.type === "create" ? `Create "${match.title}"` : match.page.title || "Untitled",
          shortcut: match.type === "create" ? "New" : "Page",
          selected: index === pageLink.selected,
          onMouseDown: () => choosePageLinkMatch(match),
        }))}
      />
    </div>
  );
}

function createWorkbookDialogState() {
  return {
    open: false,
    mode: "create",
    name: "Workbook",
    path: "",
    error: "",
    creating: false,
    browsing: false,
  };
}

function WorkbookDialog({
  open,
  mode,
  name,
  path,
  error,
  creating,
  browsing,
  inputRef,
  onMode,
  onName,
  onPath,
  onBrowse,
  onCancel,
  onSubmit,
}) {
  if (!open) return null;
  const busy = creating || browsing;
  const linking = mode === "link";
  return (
    <div
      className="page-workbook-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <form
        className="page-workbook-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pageWorkbookDialogTitle"
        onSubmit={(event) => {
          event.preventDefault();
          void onSubmit();
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          }
        }}
      >
        <div className="page-workbook-dialog-icon" aria-hidden="true">X</div>
        <div className="page-workbook-dialog-body">
          <h2 id="pageWorkbookDialogTitle">Add Excel workbook</h2>
          <div className="page-workbook-dialog-modes" role="group" aria-label="Workbook source">
            <button
              type="button"
              className={!linking ? "is-active" : ""}
              aria-pressed={!linking}
              disabled={busy}
              onClick={() => onMode("create")}
            >
              Create new
            </button>
            <button
              type="button"
              className={linking ? "is-active" : ""}
              aria-pressed={linking}
              disabled={busy}
              onClick={() => onMode("link")}
            >
              Link existing
            </button>
          </div>
          {linking ? (
            <>
              <p>Link to the original file without copying it into application storage.</p>
              <label htmlFor="pageWorkbookPath">Workbook path</label>
              <div className={`page-workbook-path-field ${error ? "has-error" : ""}`}>
                <input
                  ref={inputRef}
                  id="pageWorkbookPath"
                  type="text"
                  value={path}
                  disabled={busy}
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={2048}
                  placeholder="C:\\Projects\\Budget.xlsx"
                  aria-invalid={error ? "true" : "false"}
                  aria-describedby={error ? "pageWorkbookDialogError" : "pageWorkbookLinkNote"}
                  onChange={(event) => onPath(event.target.value)}
                />
                <button type="button" disabled={busy} onClick={() => void onBrowse()}>
                  {browsing ? "Choosing..." : "Browse..."}
                </button>
              </div>
              <p className="page-workbook-link-note" id="pageWorkbookLinkNote">
                Removing this link will not delete the original file.
              </p>
            </>
          ) : (
            <>
              <p>Create a blank workbook stored locally with this page.</p>
              <label htmlFor="pageWorkbookName">Workbook name</label>
              <div className={`page-workbook-name-field ${error ? "has-error" : ""}`}>
                <input
                  ref={inputRef}
                  id="pageWorkbookName"
                  type="text"
                  value={name}
                  disabled={busy}
                  autoComplete="off"
                  maxLength={125}
                  aria-invalid={error ? "true" : "false"}
                  aria-describedby={error ? "pageWorkbookDialogError" : undefined}
                  onChange={(event) => onName(event.target.value.replace(/\.xlsx$/i, ""))}
                />
                <span>.xlsx</span>
              </div>
            </>
          )}
          {error && (
            <div className="page-workbook-dialog-error" id="pageWorkbookDialogError" role="alert">
              {error}
            </div>
          )}
          <div className="page-workbook-dialog-actions">
            <button type="button" className="page-workbook-dialog-cancel" disabled={busy} onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="page-workbook-dialog-create" disabled={busy}>
              {creating ? (linking ? "Linking..." : "Creating...") : linking ? "Link file" : "Create"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function CommandMenu({ id, open, position, header, rows }) {
  if (!open || !rows.length) return null;
  const style = position
    ? {
        left: `${Math.max(16, position.left)}px`,
        top: `${Math.max(16, position.bottom + 8)}px`,
      }
    : {};
  return (
    <div className="page-slash-menu project-pages-menu" id={id} role="listbox" style={style}>
      <div className="page-slash-menu-header">
        <span>Commands</span>
        <span>{header}</span>
      </div>
      {rows.map((row) => (
        <button
          className={`page-slash-menu-item ${row.selected ? "is-active" : ""}`}
          type="button"
          role="option"
          aria-selected={row.selected ? "true" : "false"}
          key={row.key}
          onMouseDown={(event) => {
            event.preventDefault();
            row.onMouseDown();
          }}
        >
          <span className="page-slash-menu-label">{row.label}</span>
          <span className="page-slash-menu-shortcut">{row.shortcut}</span>
        </button>
      ))}
    </div>
  );
}

function CodeMenu({ open, position, language, onLanguage }) {
  if (!open) return null;
  const style = position
    ? {
        left: `${Math.max(16, position.left)}px`,
        top: `${Math.max(16, position.top - 44)}px`,
      }
    : {};
  return (
    <div className="page-slash-menu project-pages-menu project-pages-code-menu" style={style}>
      <select
        className="project-pages-code-language"
        aria-label="Code block language"
        value={language || ""}
        onChange={(event) => onLanguage(event.target.value)}
      >
        {CODE_LANGUAGES.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </div>
  );
}

const TABLE_ACTIONS = [
  { id: "rowAbove", label: "+Row ↑", title: "Add row above", run: (chain) => chain.addRowBefore() },
  { id: "rowBelow", label: "+Row ↓", title: "Add row below", run: (chain) => chain.addRowAfter() },
  { id: "colLeft", label: "+Col ←", title: "Add column left", run: (chain) => chain.addColumnBefore() },
  { id: "colRight", label: "+Col →", title: "Add column right", run: (chain) => chain.addColumnAfter() },
  { id: "delRow", label: "−Row", title: "Delete row", run: (chain) => chain.deleteRow() },
  { id: "delCol", label: "−Col", title: "Delete column", run: (chain) => chain.deleteColumn() },
  { id: "header", label: "Header", title: "Toggle header row", run: (chain) => chain.toggleHeaderRow() },
  { id: "delTable", label: "✕", title: "Delete table", run: (chain) => chain.deleteTable() },
];

function TableMenu({ open, position, editor }) {
  if (!open || !editor) return null;
  const style = position
    ? {
        left: `${Math.max(16, position.left)}px`,
        top: `${Math.max(16, position.top - 44)}px`,
      }
    : {};
  return (
    <div className="page-slash-menu project-pages-menu project-pages-table-menu" style={style}>
      {TABLE_ACTIONS.map((action) => (
        <button
          key={action.id}
          type="button"
          className="project-pages-table-btn"
          title={action.title}
          aria-label={action.title}
          onMouseDown={(event) => {
            event.preventDefault();
            action.run(editor.chain().focus()).run();
          }}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}

function CalloutMenu({ open, position, onEmoji, onColor }) {
  if (!open) return null;
  const style = position
    ? {
        left: `${Math.max(16, position.left)}px`,
        top: `${Math.max(16, position.top - 44)}px`,
      }
    : {};
  return (
    <div className="page-slash-menu project-pages-menu project-pages-callout-menu" style={style}>
      {CALLOUT_EMOJIS.map((emoji) => (
        <button
          key={emoji}
          type="button"
          className="project-pages-callout-btn"
          title="Callout icon"
          onMouseDown={(event) => {
            event.preventDefault();
            onEmoji(emoji);
          }}
        >
          {emoji}
        </button>
      ))}
      <span className="project-pages-callout-sep" />
      {CALLOUT_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          className={`project-pages-callout-dot callout-dot-${color}`}
          title={`${color} callout`}
          aria-label={`${color} callout`}
          onMouseDown={(event) => {
            event.preventDefault();
            onColor(color);
          }}
        />
      ))}
    </div>
  );
}

function ColorMenu({ open, mode, position, colors, onPick }) {
  if (!open) return null;
  const style = position
    ? {
        left: `${Math.max(16, position.left)}px`,
        top: `${Math.max(16, position.bottom + 8)}px`,
      }
    : {};
  return (
    <div className="page-slash-menu project-pages-menu project-pages-color-menu" role="listbox" style={style}>
      <div className="page-slash-menu-header">
        <span>{mode === "highlight" ? "Highlight" : "Text color"}</span>
        <span>Esc to close</span>
      </div>
      <div className="project-pages-color-grid">
        {colors.map((color) => (
          <button
            key={color.label}
            type="button"
            role="option"
            className="project-pages-color-swatch"
            title={color.label}
            aria-label={`${mode === "highlight" ? "Highlight" : "Text color"}: ${color.label}`}
            onMouseDown={(event) => {
              event.preventDefault();
              onPick(color.value);
            }}
          >
            <span
              className="project-pages-color-chip"
              style={mode === "highlight" ? { background: color.value || "transparent" } : { color: color.value || "inherit" }}
            >
              {color.value ? "A" : "×"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function normalizeHref(url) {
  const raw = String(url || "").trim();
  if (/^(https?:|mailto:|tel:|file:|ftp:)/i.test(raw)) return raw;
  if (/^[\w.+-]+@[\w.-]+\.\w+$/.test(raw)) return `mailto:${raw}`;
  if (/^\/\//.test(raw)) return `https:${raw}`;
  return `https://${raw}`;
}

function mount(container, options = {}) {
  if (!container) return false;
  currentOptions = options || {};
  if (root && mountedContainer !== container) {
    root.unmount();
    root = null;
  }
  mountedContainer = container;
  if (!root) root = createRoot(container);
  root.render(<PageEditorApp />);
  return true;
}

function unmount() {
  if (root) root.unmount();
  root = null;
  mountedContainer = null;
  currentContext = null;
  flushCurrentEditor = null;
}

function setDocument(pageContext) {
  currentContext = pageContext || null;
  emitContext();
}

async function flushSave() {
  if (flushCurrentEditor) await flushCurrentEditor();
}

const ProjectPagesEditorApi = { flushSave, mount, setDocument, unmount };

if (typeof window !== "undefined") {
  window.ProjectPagesEditor = ProjectPagesEditorApi;
}

export { flushSave, mount, setDocument, unmount };
