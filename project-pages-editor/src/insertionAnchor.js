// Follow edits made while a file picker/upload is pending, without following
// later caret movements. Each anchor belongs to one editor (and thus one page).
export function createInsertionAnchor(editor, position = editor.state.selection.from) {
  let current = position;
  const map = ({ transaction }) => {
    current = transaction.mapping.map(current, 1);
  };
  editor.on("transaction", map);
  return {
    get position() { return Math.min(current, editor.state.doc.content.size); },
    release() { editor.off("transaction", map); },
  };
}
