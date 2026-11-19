using System;
using System.IO;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Runtime;

namespace Acies.PrepareXrefs
{
    /// <summary>
    /// Multi-targeted (net48 + net8.0-windows) replacement for StripRefPaths.dll so
    /// AutoCAD 2020-2024 (.NET Framework 4.8) and AutoCAD 2025+ (.NET 8) both strip
    /// saved directory prefixes from images, PDF/DGN/DWF underlays, and XREFs.
    /// </summary>
    public class StripRefPathCommands
    {
        private static readonly string[] UnderlayDictNames =
        {
            "ACAD_PDFDEFINITIONS",
            "ACAD_DGNDEFINITIONS",
            "ACAD_DWFDEFINITIONS",
        };

        private static bool NeedsStrip(string rawPath, out string fileName)
        {
            fileName = null;
            if (string.IsNullOrWhiteSpace(rawPath)) return false;
            var normalized = rawPath.Trim().Replace('/', Path.DirectorySeparatorChar);
            try { fileName = Path.GetFileName(normalized); }
            catch (ArgumentException) { return false; }
            if (string.IsNullOrEmpty(fileName)) return false;
            return !string.Equals(rawPath.Trim(), fileName, StringComparison.Ordinal);
        }

        [CommandMethod("STRIPREFPATHS")]
        public static void StripRefPaths()
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return;
            var db = doc.Database;
            var ed = doc.Editor;
            int imagesUpdated = 0, underlaysUpdated = 0, xrefsUpdated = 0;

            try
            {
                using (var tr = db.TransactionManager.StartTransaction())
                {
                    // 1. Raster images
                    try
                    {
                        var imgDictId = RasterImageDef.GetImageDictionary(db);
                        if (!imgDictId.IsNull)
                        {
                            var imgDict = (DBDictionary)tr.GetObject(imgDictId, OpenMode.ForRead);
                            foreach (DBDictionaryEntry entry in imgDict)
                            {
                                try
                                {
                                    var imgDef = tr.GetObject(entry.Value, OpenMode.ForWrite) as RasterImageDef;
                                    if (imgDef == null) continue;
                                    var current = imgDef.SourceFileName;
                                    if (!NeedsStrip(current, out var fileName)) continue;
                                    imgDef.SourceFileName = fileName;
                                    imagesUpdated++;
                                    ed.WriteMessage("\n[StripRefPaths] IMAGE: '" + current + "' -> '" + fileName + "'\n");
                                }
                                catch (System.Exception ex)
                                {
                                    ed.WriteMessage("\n[StripRefPaths] [IMAGE skip] " + ex.Message + "\n");
                                }
                            }
                        }
                    }
                    catch (System.Exception ex)
                    {
                        ed.WriteMessage("\n[StripRefPaths] [Images section error] " + ex.Message + "\n");
                    }

                    // 2. PDF / DGN / DWF underlays
                    try
                    {
                        var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForRead);
                        foreach (var dictName in UnderlayDictNames)
                        {
                            if (!nod.Contains(dictName)) continue;
                            var uDict = tr.GetObject(nod.GetAt(dictName), OpenMode.ForRead) as DBDictionary;
                            if (uDict == null) continue;
                            foreach (DBDictionaryEntry entry in uDict)
                            {
                                try
                                {
                                    var uDef = tr.GetObject(entry.Value, OpenMode.ForWrite) as UnderlayDefinition;
                                    if (uDef == null) continue;
                                    var current = uDef.SourceFileName;
                                    if (!NeedsStrip(current, out var fileName)) continue;
                                    uDef.SourceFileName = fileName;
                                    underlaysUpdated++;
                                    ed.WriteMessage("\n[StripRefPaths] UNDERLAY[" + dictName + "]: '" + current + "' -> '" + fileName + "'\n");
                                }
                                catch (System.Exception ex)
                                {
                                    ed.WriteMessage("\n[StripRefPaths] [UNDERLAY skip] " + ex.Message + "\n");
                                }
                            }
                        }
                    }
                    catch (System.Exception ex)
                    {
                        ed.WriteMessage("\n[StripRefPaths] [Underlays section error] " + ex.Message + "\n");
                    }

                    // 3. XREFs
                    try
                    {
                        var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                        foreach (ObjectId btrId in bt)
                        {
                            try
                            {
                                var btr = tr.GetObject(btrId, OpenMode.ForRead) as BlockTableRecord;
                                if (btr == null || !btr.IsFromExternalReference) continue;
                                var current = btr.PathName;
                                if (!NeedsStrip(current, out var fileName)) continue;
                                btr.UpgradeOpen();
                                btr.PathName = fileName;
                                xrefsUpdated++;
                                ed.WriteMessage("\n[StripRefPaths] XREF: '" + current + "' -> '" + fileName + "'\n");
                            }
                            catch (System.Exception ex)
                            {
                                ed.WriteMessage("\n[StripRefPaths] [XREF error] " + ex.Message + "\n");
                            }
                        }
                    }
                    catch (System.Exception ex)
                    {
                        ed.WriteMessage("\n[StripRefPaths] [Xrefs section error] " + ex.Message + "\n");
                    }

                    tr.Commit();
                }

                ed.WriteMessage(
                    "\n[StripRefPaths] Done. Updated: Images=" + imagesUpdated +
                    ", Underlays=" + underlaysUpdated +
                    ", Xrefs=" + xrefsUpdated + "\n");
            }
            catch (System.Exception ex)
            {
                ed.WriteMessage("\n[StripRefPaths] [FATAL] " + ex.Message + "\n");
            }
        }
    }
}
