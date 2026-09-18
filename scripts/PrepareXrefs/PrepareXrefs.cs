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
                var worker = new Worker(Path.GetDirectoryName(output), searchRoot,
                    Environment.GetEnvironmentVariable("ACIES_XREF_PACKAGE") == "1");
                worker.Process(source, output);
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

    internal sealed class Worker
    {
        private readonly string temp;
        private readonly string searchRoot;
        private readonly bool package;
        private readonly Dictionary<string, string> completed = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> active = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        public int Bound;
        public int Exploded;

        public Worker(string temp, string searchRoot, bool package) { this.temp = temp; this.searchRoot = searchRoot; this.package = package; }

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
                                        throw new InvalidOperationException("External image or underlay in " + source + ". Prepare this drawing manually to preserve its supporting media.");
                                    if (entity is BlockReference insert && !insert.ExtensionDictionary.IsNull)
                                    {
                                        var dict = (DBDictionary)tr.GetObject(insert.ExtensionDictionary, OpenMode.ForRead);
                                        var definition = (BlockTableRecord)tr.GetObject(insert.BlockTableRecord, OpenMode.ForRead);
                                        if (definition.IsFromExternalReference && dict.Contains("ACAD_FILTER"))
                                            throw new InvalidOperationException("Clipped XREF in " + source + ". Prepare this reference manually to preserve its clipping.");
                                    }
                                }
                        }
                        tr.Commit();
                    }

                    foreach (var item in refs)
                    {
                        var child = Process(item.Value);
                        using (var tr = db.TransactionManager.StartTransaction())
                        {
                            ((BlockTableRecord)tr.GetObject(item.Key, OpenMode.ForWrite)).PathName = child;
                            tr.Commit();
                        }
                    }
                    if (refs.Count > 0)
                    {
                        var ids = new ObjectIdCollection(refs.Keys.ToArray());
                        db.ReloadXrefs(ids);
                        db.ResolveXrefs(true, false);
                        using (var tr = db.TransactionManager.StartTransaction())
                        {
                            foreach (var id in refs.Keys)
                            {
                                var block = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                                if (!block.IsResolved) throw new InvalidOperationException("Cannot resolve XREF '" + block.Name + "' in " + source);
                            }
                            tr.Commit();
                        }
                        db.BindXrefs(ids, true); // Preserve separate layer/block names on collisions.
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
