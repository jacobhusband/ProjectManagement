"""
ACIES Engineering - Unified SQLite Project Database Layer
Provides schema initialization, relational tables, JSON payload persistence,
and CRUD operations for projects, drawings, panel schedules, and compliance audits.
"""

import os
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Generator
from pathlib import Path
from contextlib import contextmanager

# Default database location if none specified
DEFAULT_DB_DIR = Path.home() / ".acies"
DEFAULT_DB_FILE = str(DEFAULT_DB_DIR / "acies_project.db")


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates a thread-safe connection to the SQLite database with WAL enabled."""
    target_path = db_path or os.environ.get("ACIES_DB_PATH", DEFAULT_DB_FILE)
    db_file = Path(target_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(db_file), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextmanager
def db_session(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that handles commit/rollback and ensures the connection is closed."""
    conn = get_db_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes all database tables and indexes."""
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        
        # 1. Projects Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            project_number TEXT UNIQUE NOT NULL,
            project_name TEXT NOT NULL,
            project_path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # 2. Drawings Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS drawings (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            dwg_path TEXT UNIQUE NOT NULL,
            sheet_number TEXT,
            sheet_title TEXT,
            last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        """)
        
        # 3. Panel Schedules Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS panel_schedules (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            dwg_id TEXT,
            panel_name TEXT NOT NULL,
            voltage TEXT,
            phase INTEGER,
            wire INTEGER,
            main_bus_amps INTEGER,
            main_type TEXT,
            main_breaker_amps INTEGER,
            aic_rating INTEGER,
            location TEXT,
            ole_handle TEXT,
            workbook_path TEXT,
            validation_status TEXT DEFAULT 'VALID',
            diagnostics_json TEXT DEFAULT '[]',
            load_summary_json TEXT,
            raw_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (dwg_id) REFERENCES drawings(id) ON DELETE SET NULL,
            UNIQUE(project_id, panel_name)
        );
        """)

        # One linked Excel panel-schedule workbook per task-list project. This
        # table intentionally does not require a projects-table foreign key:
        # older task-list projects may not yet have been mirrored into the
        # unified projects table, but still need a durable workbook binding.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS panel_workbook_bindings (
            project_id TEXT PRIMARY KEY,
            workbook_path TEXT NOT NULL,
            last_synced_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # 4. Circuits Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS circuits (
            id TEXT PRIMARY KEY,
            panel_id TEXT NOT NULL,
            circuit_number INTEGER NOT NULL,
            phase_pole TEXT NOT NULL,
            load_description TEXT NOT NULL,
            load_type TEXT NOT NULL,
            breaker_amps INTEGER NOT NULL,
            poles INTEGER NOT NULL DEFAULT 1,
            wire_gauge TEXT DEFAULT '#12 AWG',
            conduit_size TEXT DEFAULT '3/4" C',
            connected_va REAL DEFAULT 0.0,
            demand_va REAL DEFAULT 0.0,
            room_zone TEXT,
            FOREIGN KEY (panel_id) REFERENCES panel_schedules(id) ON DELETE CASCADE,
            UNIQUE(panel_id, circuit_number)
        );
        """)
        
        # 5. Title 24 Spaces Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS title24_spaces (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            dwg_id TEXT,
            room_number TEXT NOT NULL,
            room_name TEXT,
            area_sqft REAL,
            space_category TEXT,
            allowed_lpd REAL,
            actual_lpd REAL,
            compliance_status TEXT DEFAULT 'COMPLIANT',
            raw_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (dwg_id) REFERENCES drawings(id) ON DELETE SET NULL,
            UNIQUE(project_id, room_number)
        );
        """)
        
        # 6. Submittal Reviews Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS submittal_reviews (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            submittal_name TEXT NOT NULL,
            spec_section TEXT,
            review_status TEXT NOT NULL,
            report_json TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        """)
        
        # Indexes for fast querying
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_drawings_project ON drawings(project_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_panels_project ON panel_schedules(project_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_circuits_panel ON circuits(panel_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_t24_project ON title24_spaces(project_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_submittals_project ON submittal_reviews(project_id);")


# ==============================================================================
# PROJECT CRUD OPERATIONS
# ==============================================================================

def upsert_project(project_number: str, project_name: str, project_path: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Inserts or updates a project record."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM projects WHERE project_number = ?", (project_number,))
        row = cursor.fetchone()
        if row:
            proj_id = row["id"]
            cursor.execute("""
                UPDATE projects 
                SET project_name = ?, project_path = ?, updated_at = ?
                WHERE id = ?
            """, (project_name, project_path, now, proj_id))
        else:
            proj_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO projects (id, project_number, project_name, project_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (proj_id, project_number, project_name, project_path, now, now))
            
    return get_project(proj_id, db_path)


def get_project(project_id_or_number: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a project by ID or project number."""
    init_db(db_path)
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM projects 
            WHERE id = ? OR project_number = ?
        """, (project_id_or_number, project_id_or_number))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def list_projects(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all projects ordered by updated_at descending."""
    init_db(db_path)
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects ORDER BY updated_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def delete_project(project_id_or_number: str, db_path: Optional[str] = None) -> bool:
    """Deletes a project record and cascades deletion of drawings, panel schedules, etc."""
    init_db(db_path)
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM projects
            WHERE id = ? OR project_number = ?
        """, (str(project_id_or_number or ""), str(project_id_or_number or "")))
        return cursor.rowcount > 0


# ==============================================================================
# DRAWING CRUD OPERATIONS
# ==============================================================================

def upsert_drawing(project_id: str, dwg_path: str, sheet_number: Optional[str] = None, 
                   sheet_title: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Inserts or updates a DWG drawing record."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM drawings WHERE dwg_path = ?", (dwg_path,))
        row = cursor.fetchone()
        if row:
            dwg_id = row["id"]
            cursor.execute("""
                UPDATE drawings 
                SET project_id = ?, sheet_number = COALESCE(?, sheet_number), 
                    sheet_title = COALESCE(?, sheet_title), last_scanned = ?
                WHERE id = ?
            """, (project_id, sheet_number, sheet_title, now, dwg_id))
        else:
            dwg_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO drawings (id, project_id, dwg_path, sheet_number, sheet_title, last_scanned)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (dwg_id, project_id, dwg_path, sheet_number, sheet_title, now))
    
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM drawings WHERE id = ?", (dwg_id,))
        return dict(cursor.fetchone())


# ==============================================================================
# PANEL SCHEDULE CRUD & SYNC OPERATIONS
# ==============================================================================

def upsert_panel_schedule(project_id: str, panel_data: Dict[str, Any], 
                          dwg_id: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Inserts or updates a panel schedule and its associated circuits in a single transaction.
    """
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    panel_name = panel_data.get("panelName")
    if not panel_name:
        raise ValueError("panelName is required in panel_data")
        
    voltage = panel_data.get("voltage")
    phase = panel_data.get("phase")
    wire = panel_data.get("wire")
    main_bus_amps = panel_data.get("mainBusRatingAmps")
    main_type = panel_data.get("mainType")
    main_breaker_amps = panel_data.get("mainBreakerAmps")
    aic_rating = panel_data.get("shortCircuitCurrentRatingAIC")
    location = panel_data.get("location")
    ole_handle = panel_data.get("oleHandle")
    workbook_path = panel_data.get("excelWorkbookPath")
    validation_status = panel_data.get("validationStatus", "VALID")
    diagnostics = panel_data.get("diagnostics", [])
    diagnostics_json = json.dumps(diagnostics)
    load_summary_json = json.dumps(panel_data.get("loadSummary", {}))
    raw_json = json.dumps(panel_data)

    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM panel_schedules 
            WHERE project_id = ? AND panel_name = ?
        """, (project_id, panel_name))
        row = cursor.fetchone()
        
        if row:
            panel_id = row["id"]
            cursor.execute("""
                UPDATE panel_schedules 
                SET dwg_id = COALESCE(?, dwg_id), voltage = ?, phase = ?, wire = ?, 
                    main_bus_amps = ?, main_type = ?, main_breaker_amps = ?, 
                    aic_rating = ?, location = ?, ole_handle = COALESCE(?, ole_handle), 
                    workbook_path = COALESCE(?, workbook_path), validation_status = ?, 
                    diagnostics_json = ?, load_summary_json = ?, raw_json = ?, updated_at = ?
                WHERE id = ?
            """, (dwg_id, voltage, phase, wire, main_bus_amps, main_type, main_breaker_amps,
                  aic_rating, location, ole_handle, workbook_path, validation_status,
                  diagnostics_json, load_summary_json, raw_json, now, panel_id))
        else:
            panel_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO panel_schedules (
                    id, project_id, dwg_id, panel_name, voltage, phase, wire,
                    main_bus_amps, main_type, main_breaker_amps, aic_rating,
                    location, ole_handle, workbook_path, validation_status,
                    diagnostics_json, load_summary_json, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (panel_id, project_id, dwg_id, panel_name, voltage, phase, wire,
                  main_bus_amps, main_type, main_breaker_amps, aic_rating,
                  location, ole_handle, workbook_path, validation_status,
                  diagnostics_json, load_summary_json, raw_json, now))
        
        # Replace circuits
        cursor.execute("DELETE FROM circuits WHERE panel_id = ?", (panel_id,))
        circuits = panel_data.get("circuits", [])
        for ckt in circuits:
            ckt_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO circuits (
                    id, panel_id, circuit_number, phase_pole, load_description,
                    load_type, breaker_amps, poles, wire_gauge, conduit_size,
                    connected_va, demand_va, room_zone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ckt_id,
                panel_id,
                int(ckt.get("circuitNumber", 0)),
                str(ckt.get("phasePole", "A")),
                str(ckt.get("loadDescription", "")),
                str(ckt.get("loadType", "SPARE")),
                int(ckt.get("breakerAmps", 20)),
                int(ckt.get("poles", 1)),
                str(ckt.get("wireGauge", "#12 AWG")),
                str(ckt.get("conduitSize", '3/4" C')),
                float(ckt.get("connectedVA", 0.0) or 0.0),
                float(ckt.get("demandVA", 0.0) or 0.0),
                str(ckt.get("roomOrZone", ""))
            ))
            
    return get_panel_schedule(panel_id, db_path)


def get_panel_schedule(panel_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a panel schedule with its circuits and parsed load summary."""
    init_db(db_path)
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM panel_schedules WHERE id = ?", (panel_id,))
        panel_row = cursor.fetchone()
        if not panel_row:
            return None
            
        panel = dict(panel_row)
        panel["diagnostics"] = json.loads(panel["diagnostics_json"] or "[]")
        panel["loadSummary"] = json.loads(panel["load_summary_json"] or "{}")
        
        cursor.execute("""
            SELECT * FROM circuits 
            WHERE panel_id = ? 
            ORDER BY circuit_number ASC
        """, (panel_id,))
        panel["circuits"] = [dict(r) for r in cursor.fetchall()]
        return panel


def list_panel_schedules(project_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all panel schedules for a given project."""
    init_db(db_path)
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, project_id, dwg_id, panel_name, voltage, phase, wire,
                   main_bus_amps, main_type, main_breaker_amps, aic_rating,
                   location, ole_handle, workbook_path, validation_status,
                   diagnostics_json, load_summary_json, updated_at
            FROM panel_schedules 
            WHERE project_id = ? 
            ORDER BY panel_name ASC
        """, (project_id,))
        panels = []
        for r in cursor.fetchall():
            p = dict(r)
            p["diagnostics"] = json.loads(p["diagnostics_json"] or "[]")
            p["loadSummary"] = json.loads(p["load_summary_json"] or "{}")
            panels.append(p)
        return panels


def delete_panel_schedule(panel_id: str, db_path: Optional[str] = None) -> bool:
    """Deletes a panel schedule and cascades circuit deletion."""
    init_db(db_path)
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM panel_schedules WHERE id = ?", (panel_id,))
        return cursor.rowcount > 0


def set_panel_workbook_binding(
    project_id: str,
    workbook_path: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist the Excel workbook linked to a project panel-schedule editor."""
    init_db(db_path)
    project_key = str(project_id or "").strip()
    raw_path = str(workbook_path or "").strip()
    if not project_key:
        raise ValueError("project_id is required")
    if not raw_path:
        raise ValueError("workbook_path is required")
    normalized_path = os.path.abspath(raw_path)
    now = datetime.now(timezone.utc).isoformat()
    with db_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO panel_workbook_bindings (
                project_id, workbook_path, last_synced_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                workbook_path = excluded.workbook_path,
                last_synced_at = excluded.last_synced_at,
                updated_at = excluded.updated_at
            """,
            (project_key, normalized_path, now, now, now),
        )
    return get_panel_workbook_binding(project_key, db_path=db_path) or {}


def get_panel_workbook_binding(
    project_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the linked panel workbook for a project, if one is configured."""
    init_db(db_path)
    project_key = str(project_id or "").strip()
    if not project_key:
        return None
    with db_session(db_path) as conn:
        row = conn.execute(
            """
            SELECT project_id, workbook_path, last_synced_at, created_at, updated_at
            FROM panel_workbook_bindings
            WHERE project_id = ?
            """,
            (project_key,),
        ).fetchone()
        return dict(row) if row else None
