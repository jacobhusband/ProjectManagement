using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.ApplicationServices.Core;

namespace Acies.PrepareXrefs
{
    public class Commands
    {
        [CommandMethod("ACIESPREPAREXREFS")]
        public static void Prepare()
        {
            var editor = Application.DocumentManager.MdiActiveDocument.Editor;
            try
            {
                var source = Environment.GetEnvironmentVariable("ACIES_XREF_SOURCE");
                var output = Environment.GetEnvironmentVariable("ACIES_XREF_OUTPUT");
                var searchRoot = Environment.GetEnvironmentVariable("ACIES_XREF_SEARCH_ROOT");
                var package = Environment.GetEnvironmentVariable("ACIES_XREF_PACKAGE") == "1";
                var worker = new Worker(Path.GetDirectoryName(output), searchRoot, package, true);
                try { worker.Process(source, output); }
                catch (BindFailedException problem)
                {
                    // A failed bind leaves the in-memory drawings unusable, so start over from the
                    // originals with prefixed names, which some drawings need to bind at all.
                    editor.WriteMessage("\nPROGRESS: WARNING: Binding with merged names failed (" + problem.Message + "). Retrying with prefixed names.\n");
                    worker = new Worker(Path.GetDirectoryName(output), searchRoot, package, false);
                    worker.Process(source, output);
                }
                // A success file, rather than Core Console's exit code, gates delivery.
                File.WriteAllText(output + ".ready", "Prepared successfully");
                editor.WriteMessage("\nACIES_XREF_PREPARED: " + worker.Bound + " bound; " + worker.Exploded + " modelspace references exploded.\n");
            }
            catch (System.Exception error)
            {
                editor.WriteMessage("\nPROGRESS: ERROR: XREF preparation failed: " + error.Message + "\n");
            }
        }
    }

    // A reference that cannot be faithfully bound and exploded. As a nested dependency it stays
    // attached as an XREF; as the selected drawing it still fails, since nothing else can carry it.
    internal sealed class UnbindableException : InvalidOperationException
    {
        public UnbindableException(string message) : base(message) { }
    }

    internal sealed class BindFailedException : InvalidOperationException
    {
        public BindFailedException(string message) : base(message) { }
    }

    internal sealed class Worker
    {
        private readonly string temp;
        private readonly string searchRoot;
        private readonly bool package;
        private readonly bool insertBind;
        private readonly Dictionary<string, string> completed = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> active = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, string> unbindable = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public int Bound;
        public int Exploded;

        public Worker(string temp, string searchRoot, bool package, bool insertBind)
        {
            this.temp = temp; this.searchRoot = searchRoot; this.package = package; this.insertBind = insertBind;
        }

        private bool Available(string candidate) => File.Exists(candidate) && (!package ||
            Path.GetFullPath(candidate).StartsWith(Path.GetFullPath(searchRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase));

        private string Resolve(string owner, string reference)
        {
            var relative = reference.Replace('/', Path.DirectorySeparatorChar);
            var candidate = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(owner), relative));
            if (Available(candidate)) return candidate;
            candidate = Path.Combine(Path.GetDirectoryName(owner), Path.GetFileName(relative));
            if (Available(candidate)) return candidate;
            // Old architect absolute paths are common in ZIPs. Only accept an unambiguous match.
            if (!string.IsNullOrEmpty(searchRoot))
            {
                var matches = Directory.EnumerateFiles(searchRoot, "*", SearchOption.AllDirectories)
                    .Where(p => string.Equals(Path.GetFileName(p), Path.GetFileName(relative), StringComparison.OrdinalIgnoreCase)).Take(2).ToArray();
                if (matches.Length == 1) return matches[0];
                if (matches.Length > 1) throw new InvalidOperationException("Ambiguous reference '" + reference + "' in " + owner);
            }
            return null;
        }

        private void DetachMissing(Database db, string source)
        {
            var missingXrefs = new List<ObjectId>();
            var missingMedia = new HashSet<ObjectId>();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (ObjectId id in (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead))
                {
                    var block = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                    if (block.IsFromExternalReference)
                    {
                        if (block.GetBlockReferenceIds(true, false).Count > 0 && Resolve(source, block.PathName) == null)
                        {
                            missingXrefs.Add(id);
                            ReportDetached("XREF", block.PathName, source);
                        }
                        continue;
                    }
                    if (block.IsDependent) continue;
                    foreach (ObjectId entityId in block)
                    {
                        var entity = tr.GetObject(entityId, OpenMode.ForRead);
                        ObjectId definitionId;
                        string path;
                        if (entity is RasterImage image && !(entity is Wipeout))
                        {
                            definitionId = image.ImageDefId;
                            if (definitionId.IsNull) continue;
                            path = ((RasterImageDef)tr.GetObject(definitionId, OpenMode.ForRead)).SourceFileName;
                        }
                        else if (entity is UnderlayReference underlay)
                        {
                            definitionId = underlay.DefinitionId;
                            if (definitionId.IsNull) continue;
                            path = ((UnderlayDefinition)tr.GetObject(definitionId, OpenMode.ForRead)).SourceFileName;
                        }
                        else continue;
                        if (Resolve(source, path) != null) continue;
                        entity.UpgradeOpen();
                        entity.Erase();
                        if (missingMedia.Add(definitionId)) ReportDetached("image/underlay", path, source);
                    }
                }
                foreach (var id in missingMedia) tr.GetObject(id, OpenMode.ForWrite).Erase();
                tr.Commit();
            }
            foreach (var id in missingXrefs) db.DetachXref(id);
        }

        private static void ReportDetached(string kind, string path, string source)
        {
            Application.DocumentManager.MdiActiveDocument.Editor.WriteMessage(
                "\nPROGRESS: Detached missing " + kind + " '" + path + "' from " + source + "\n");
        }

        public string Process(string source, string requestedOutput = null)
        {
            source = Path.GetFullPath(source);
            if (completed.TryGetValue(source, out var cached)) return cached;
            if (unbindable.TryGetValue(source, out var reason)) throw new UnbindableException(reason);
            // Only nested dependencies get bound; the selected drawing (explicit output) is just saved.
            var nested = requestedOutput == null;
            if (!active.Add(source)) throw new InvalidOperationException("Circular XREF dependency: " + source);
            if (active.Count > 64) throw new InvalidOperationException("XREF nesting exceeds 64 drawings: " + source);
            var output = requestedOutput ?? Path.Combine(temp, Guid.NewGuid().ToString("N") + ".dwg");
            using (var db = new Database(false, true))
            {
                db.ReadDwgFile(source, FileOpenMode.OpenForReadAndAllShare, false, null);
                db.CloseInput(true);
                var previous = HostApplicationServices.WorkingDatabase;
                try
                {
                    HostApplicationServices.WorkingDatabase = db;
                    DetachMissing(db, source);
                    var refs = new Dictionary<ObjectId, string>();
                    using (var tr = db.TransactionManager.StartTransaction())
                    {
                        foreach (ObjectId id in (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead))
                        {
                            var block = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                            // Cached nested definitions can report IsDependent=false before reload.
                            // Only definitions with inserts in this database are direct dependencies.
                            if (block.IsFromExternalReference && block.GetBlockReferenceIds(true, false).Count > 0)
                            {
                                if (block.IsUnloaded) throw new InvalidOperationException("Unloaded XREF '" + block.Name + "' in " + source + ". Load it before preparation.");
                                refs.Add(id, Resolve(source, block.PathName) ??
                                    throw new FileNotFoundException("Reference disappeared during preparation: " + block.PathName));
                            }
                            if (!block.IsFromExternalReference && !block.IsDependent)
                                foreach (ObjectId entityId in block)
                                {
                                    var entity = tr.GetObject(entityId, OpenMode.ForRead);
                                    if ((entity is RasterImage && !(entity is Wipeout)) || entity is UnderlayReference)
                                        throw new UnbindableException("External image or underlay in " + source + ". Prepare this drawing manually to preserve its supporting media.");
                                    // AutoCAD refuses to bind an XREF holding proxy (e.g. AEC) objects.
                                    if (nested && entity is ProxyEntity)
                                        throw new UnbindableException("Proxy objects in " + source + " cannot be bound.");
                                    if (entity is BlockReference insert && !insert.ExtensionDictionary.IsNull)
                                    {
                                        var dict = (DBDictionary)tr.GetObject(insert.ExtensionDictionary, OpenMode.ForRead);
                                        var definition = (BlockTableRecord)tr.GetObject(insert.BlockTableRecord, OpenMode.ForRead);
                                        if (definition.IsFromExternalReference && dict.Contains("ACAD_FILTER"))
                                            throw new UnbindableException("Clipped XREF in " + source + ". Prepare this reference manually to preserve its clipping.");
                                    }
                                }
                        }
                        tr.Commit();
                    }

                    foreach (var item in refs.ToArray())
                    {
                        string child;
                        try { child = Process(item.Value); }
                        catch (UnbindableException problem)
                        {
                            // Keep the reference attached instead of losing its display. It resolves
                            // by file name from Xrefs once the drawing is transferred there.
                            var childPath = Path.GetFullPath(item.Value);
                            active.Remove(childPath);
                            unbindable[childPath] = problem.Message;
                            refs.Remove(item.Key);
                            var console = Application.DocumentManager.MdiActiveDocument.Editor;
                            console.WriteMessage("\nPROGRESS: WARNING: Left XREF '" + Path.GetFileName(childPath) + "' attached: " + problem.Message + "\n");
                            console.WriteMessage("\nACIES_XREF_KEPT: " + childPath + "\n");
                            continue;
                        }
                        using (var tr = db.TransactionManager.StartTransaction())
                        {
                            ((BlockTableRecord)tr.GetObject(item.Key, OpenMode.ForWrite)).PathName = child;
                            tr.Commit();
                        }
                    }
                    if (refs.Count > 0)
                    {
                        var ids = new ObjectIdCollection(refs.Keys.ToArray());
                        // ReloadXrefs alone picks up the repointed paths. Following it with ResolveXrefs
                        // makes BindXrefs fail with eWasErased on drawings that carry AEC objects.
                        db.ReloadXrefs(ids);
                        using (var tr = db.TransactionManager.StartTransaction())
                        {
                            foreach (var id in refs.Keys)
                            {
                                var block = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                                if (!block.IsResolved) throw new InvalidOperationException("Cannot resolve XREF '" + block.Name + "' in " + source);
                            }
                            tr.Commit();
                        }
                        try { db.BindXrefs(ids, insertBind); }
                        catch (Autodesk.AutoCAD.Runtime.Exception error)
                        {
                            throw new BindFailedException(error.Message);
                        }
                        using (var tr = db.TransactionManager.StartTransaction())
                        {
                            foreach (var id in refs.Keys)
                            {
                                var block = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                                if (block.IsFromExternalReference) throw new InvalidOperationException("XREF failed to bind: " + block.Name);
                            }
                            var table = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                            var model = (BlockTableRecord)tr.GetObject(table[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                            foreach (ObjectId id in model.Cast<ObjectId>().ToArray())
                            {
                                var insert = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                                if (insert == null || !refs.ContainsKey(insert.BlockTableRecord)) continue;
                                insert.UpgradeOpen();
                                using (var pieces = new DBObjectCollection())
                                {
                                    insert.Explode(pieces);
                                    try
                                    {
                                        var definition = (BlockTableRecord)tr.GetObject(insert.BlockTableRecord, OpenMode.ForRead);
                                        if (pieces.Count == 0 && definition.Cast<ObjectId>().Any())
                                            throw new InvalidOperationException("Explosion produced no geometry in " + source);
                                        foreach (DBObject piece in pieces)
                                        {
                                            if (!(piece is Entity entity)) throw new InvalidOperationException("Unsupported exploded object in " + source);
                                            model.AppendEntity(entity);
                                            tr.AddNewlyCreatedDBObject(entity, true);
                                        }
                                    }
                                    finally { foreach (DBObject piece in pieces) if (piece.ObjectId.IsNull) piece.Dispose(); }
                                }
                                insert.Erase();
                                Exploded++;
                            }
                            tr.Commit();
                        }
                        Bound += refs.Count;
                    }
                    db.SaveAs(output, DwgVersion.Current);
                }
                finally { HostApplicationServices.WorkingDatabase = previous; }
            }
            active.Remove(source);
            completed.Add(source, output);
            return output;
        }
    }
}
