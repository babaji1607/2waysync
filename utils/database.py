"""
SQLite database for lead-to-card mapping and sync tracking
Provides persistent storage for relationship between Google Sheets leads and Trello cards
"""

import sqlite3
import os
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from utils.logger import setup_logger

logger = setup_logger(__name__)

DB_PATH = "sync_mapping.db"


class SyncDatabase:
    """SQLite database for managing lead-card mappings and sync history"""

    def __init__(self, db_path: str = DB_PATH):
        """
        Initialize database connection

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database with required tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Lead-Card Mapping table (central authority)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lead_card_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT NOT NULL UNIQUE,
                    lead_name TEXT NOT NULL,
                    lead_email TEXT NOT NULL,
                    lead_phone TEXT,
                    lead_company TEXT,
                    card_id TEXT NOT NULL UNIQUE,
                    card_title TEXT NOT NULL,
                    trello_list_id TEXT NOT NULL,
                    current_status TEXT NOT NULL DEFAULT 'New',
                    last_synced_status TEXT,
                    last_sync_source TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Add missing columns to existing tables (migration)
            cursor.execute("PRAGMA table_info(lead_card_mapping)")
            columns = [column[1] for column in cursor.fetchall()]
            
            # Add missing columns if they don't exist
            if 'lead_phone' not in columns:
                cursor.execute("ALTER TABLE lead_card_mapping ADD COLUMN lead_phone TEXT")
                logger.info("Added lead_phone column to lead_card_mapping")
            
            if 'lead_company' not in columns:
                cursor.execute("ALTER TABLE lead_card_mapping ADD COLUMN lead_company TEXT")
                logger.info("Added lead_company column to lead_card_mapping")
            
            if 'current_status' not in columns:
                cursor.execute("ALTER TABLE lead_card_mapping ADD COLUMN current_status TEXT NOT NULL DEFAULT 'New'")
                logger.info("Added current_status column to lead_card_mapping")
            
            if 'last_sync_source' not in columns:
                cursor.execute("ALTER TABLE lead_card_mapping ADD COLUMN last_sync_source TEXT")
                logger.info("Added last_sync_source column to lead_card_mapping")

            # Sync History table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT,
                    card_id TEXT,
                    action TEXT,  -- 'create', 'update', 'delete', 'move'
                    old_status TEXT,
                    new_status TEXT,
                    source TEXT,  -- 'sheets' or 'trello'
                    success BOOLEAN,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Status Mapping table (configuration)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS status_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sheet_status TEXT NOT NULL UNIQUE,
                    trello_list_id TEXT NOT NULL,
                    trello_list_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logger.info("Database initialized successfully")

        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {str(e)}")
            raise

        finally:
            if conn:
                conn.close()

    def add_mapping(
        self,
        lead_id: str,
        lead_name: str,
        lead_email: str,
        card_id: str,
        card_title: str,
        trello_list_id: str,
        status: str = "NEW",
    ) -> bool:
        """
        Add or update lead-to-card mapping

        Args:
            lead_id: Google Sheets lead ID
            lead_name: Lead name
            lead_email: Lead email
            card_id: Trello card ID
            card_title: Trello card title
            trello_list_id: Trello list ID
            status: Current status

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT OR REPLACE INTO lead_card_mapping
                (lead_id, lead_name, lead_email, card_id, card_title, trello_list_id, last_synced_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (lead_id, lead_name, lead_email, card_id, card_title, trello_list_id, status, datetime.now()),
            )

            conn.commit()
            logger.info(
                f"Added mapping: Lead {lead_id} → Card {card_id}",
                extra={"extra_data": {"lead_id": lead_id, "card_id": card_id}},
            )
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to add mapping: {str(e)}")
            return False

        finally:
            if conn:
                conn.close()

    def get_mapping_by_lead_id(self, lead_id: str) -> Optional[Dict]:
        """
        Get card mapping for a lead

        Args:
            lead_id: Google Sheets lead ID

        Returns:
            Mapping dict or None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM lead_card_mapping WHERE lead_id = ?",
                (lead_id,),
            )
            row = cursor.fetchone()

            if row:
                return dict(row)
            return None

        except sqlite3.Error as e:
            logger.error(f"Failed to get mapping: {str(e)}")
            return None

        finally:
            if conn:
                conn.close()

    def get_mapping_by_card_id(self, card_id: str) -> Optional[Dict]:
        """
        Get lead mapping for a card

        Args:
            card_id: Trello card ID

        Returns:
            Mapping dict or None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM lead_card_mapping WHERE card_id = ?",
                (card_id,),
            )
            row = cursor.fetchone()

            if row:
                return dict(row)
            return None

        except sqlite3.Error as e:
            logger.error(f"Failed to get mapping: {str(e)}")
            return None

        finally:
            if conn:
                conn.close()

    def get_all_mappings(self) -> List[Dict]:
        """
        Get all lead-card mappings

        Returns:
            List of mapping dicts
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM lead_card_mapping")
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"Failed to get mappings: {str(e)}")
            return []

        finally:
            if conn:
                conn.close()

    def delete_mapping(self, lead_id: str = None, card_id: str = None) -> bool:
        """
        Delete a mapping

        Args:
            lead_id: Google Sheets lead ID
            card_id: Trello card ID

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if lead_id:
                cursor.execute("DELETE FROM lead_card_mapping WHERE lead_id = ?", (lead_id,))
            elif card_id:
                cursor.execute("DELETE FROM lead_card_mapping WHERE card_id = ?", (card_id,))
            else:
                return False

            conn.commit()
            logger.info(f"Deleted mapping: lead_id={lead_id}, card_id={card_id}")
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to delete mapping: {str(e)}")
            return False

        finally:
            if conn:
                conn.close()

    def add_sync_history(
        self,
        action: str,
        lead_id: str = None,
        card_id: str = None,
        old_status: str = None,
        new_status: str = None,
        source: str = "sheets",
        success: bool = True,
        error_message: str = None,
    ) -> bool:
        """
        Record sync action in history

        Args:
            action: Action type (create, update, delete, move)
            lead_id: Google Sheets lead ID
            card_id: Trello card ID
            old_status: Previous status
            new_status: New status
            source: Where change came from (sheets or trello)
            success: Whether action succeeded
            error_message: Error message if failed

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO sync_history
                (lead_id, card_id, action, old_status, new_status, source, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (lead_id, card_id, action, old_status, new_status, source, success, error_message),
            )

            conn.commit()
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to record sync history: {str(e)}")
            return False

        finally:
            if conn:
                conn.close()

    def get_sync_history(self, limit: int = 100) -> List[Dict]:
        """
        Get recent sync history

        Args:
            limit: Number of records to return

        Returns:
            List of history records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM sync_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"Failed to get sync history: {str(e)}")
            return []

        finally:
            if conn:
                conn.close()

    def set_status_mapping(self, sheet_status: str, trello_list_id: str, trello_list_name: str) -> bool:
        """
        Set mapping between sheet status and trello list

        Args:
            sheet_status: Status value in Google Sheets (e.g., "NEW", "CONTACTED")
            trello_list_id: Trello list ID
            trello_list_name: Trello list name

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT OR REPLACE INTO status_mapping
                (sheet_status, trello_list_id, trello_list_name)
                VALUES (?, ?, ?)
            """,
                (sheet_status, trello_list_id, trello_list_name),
            )

            conn.commit()
            logger.info(
                f"Set status mapping: {sheet_status} → {trello_list_name}",
                extra={"extra_data": {"sheet_status": sheet_status, "list_id": trello_list_id}},
            )
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to set status mapping: {str(e)}")
            return False

        finally:
            if conn:
                conn.close()

    def get_status_mapping(self, sheet_status: str = None) -> Optional[Dict]:
        """
        Get status mapping

        Args:
            sheet_status: Sheet status to look up

        Returns:
            Mapping dict or None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if sheet_status:
                cursor.execute(
                    "SELECT * FROM status_mapping WHERE sheet_status = ?",
                    (sheet_status,),
                )
            else:
                cursor.execute("SELECT * FROM status_mapping")

            row = cursor.fetchone() if sheet_status else cursor.fetchall()

            if sheet_status:
                return dict(row) if row else None
            else:
                return [dict(r) for r in row] if row else []

        except sqlite3.Error as e:
            logger.error(f"Failed to get status mapping: {str(e)}")
            return None if sheet_status else []

        finally:
            if conn:
                conn.close()

    def get_all_status_mappings(self) -> List[Dict]:
        """
        Get all status mappings

        Returns:
            List of status mappings
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM status_mapping")
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"Failed to get status mappings: {str(e)}")
            return []

        finally:
            if conn:
                conn.close()

    def upsert_record_from_sheets(
        self,
        lead_id: str,
        lead_name: str,
        lead_email: str,
        lead_phone: str,
        lead_company: str,
        current_status: str,
    ) -> tuple[bool, str, Optional[Dict]]:
        """
        Upsert record when data is received from Google Sheets
        Central authority: Google Sheets data is always inserted/updated
        
        Returns:
            (success, action, record) where action is 'created' or 'updated'
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Check if record exists
            cursor.execute("SELECT * FROM lead_card_mapping WHERE lead_id = ?", (lead_id,))
            existing = cursor.fetchone()

            if existing:
                # Record exists - update it with latest data from Sheets
                cursor.execute(
                    """
                    UPDATE lead_card_mapping 
                    SET lead_name = ?, lead_email = ?, lead_phone = ?, lead_company = ?,
                        current_status = ?, last_sync_source = ?, updated_at = ?
                    WHERE lead_id = ?
                    """,
                    (lead_name, lead_email, lead_phone, lead_company, current_status, 'sheets', datetime.now(), lead_id)
                )
                conn.commit()
                
                cursor.execute("SELECT * FROM lead_card_mapping WHERE lead_id = ?", (lead_id,))
                updated_record = dict(cursor.fetchone())
                
                print(f"✓ Updated existing record: {lead_id}")
                logger.info(f"Updated record from Sheets: {lead_id}")
                return (True, 'updated', updated_record)
            else:
                # NEW: Record doesn't exist - create it with unique placeholder card_id (will be updated when card is created)
                # This makes Google Sheets the central authority - all data is immediately stored
                # Use unique placeholder: PENDING_{lead_id}
                pending_card_id = f"PENDING_{lead_id}"
                cursor.execute(
                    """
                    INSERT INTO lead_card_mapping
                    (lead_id, lead_name, lead_email, lead_phone, lead_company, 
                     card_id, card_title, trello_list_id, current_status, last_sync_source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (lead_id, lead_name, lead_email, lead_phone, lead_company,
                     pending_card_id, f'{lead_name} (pending)', 'PENDING', current_status, 'sheets', datetime.now())
                )
                conn.commit()
                
                cursor.execute("SELECT * FROM lead_card_mapping WHERE lead_id = ?", (lead_id,))
                created_record = dict(cursor.fetchone())
                
                print(f"✓ Created new record: {lead_id}")
                logger.info(f"Created new record from Sheets: {lead_id}")
                return (True, 'created', created_record)

        except sqlite3.Error as e:
            logger.error(f"Failed to upsert record from sheets: {str(e)}")
            print(f"✗ Database error: {str(e)}")
            return (False, 'error', None)
        finally:
            if conn:
                conn.close()

    def create_record_with_card(
        self,
        lead_id: str,
        lead_name: str,
        lead_email: str,
        lead_phone: str,
        lead_company: str,
        card_id: str,
        card_title: str,
        trello_list_id: str,
        current_status: str,
    ) -> tuple[bool, Optional[Dict]]:
        """
        Create a new record with card when lead is synced to Trello
        
        Returns:
            (success, record)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO lead_card_mapping
                (lead_id, lead_name, lead_email, lead_phone, lead_company, 
                 card_id, card_title, trello_list_id, current_status, last_sync_source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (lead_id, lead_name, lead_email, lead_phone, lead_company,
                 card_id, card_title, trello_list_id, current_status, 'sheets', datetime.now())
            )
            conn.commit()

            cursor.execute("SELECT * FROM lead_card_mapping WHERE lead_id = ?", (lead_id,))
            record = dict(cursor.fetchone())
            
            logger.info(f"Created new record with card: {lead_id} → {card_id}")
            return (True, record)

        except sqlite3.Error as e:
            logger.error(f"Failed to create record with card: {str(e)}")
            return (False, None)
        finally:
            if conn:
                conn.close()

    def update_from_trello_move(
        self,
        card_id: str,
        new_list_id: str,
        new_status: str,
    ) -> tuple[bool, Optional[Dict]]:
        """
        Update record when card is moved in Trello
        Central authority: Database updates and provides truth
        
        Returns:
            (success, updated_record)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Update the record
            cursor.execute(
                """
                UPDATE lead_card_mapping 
                SET trello_list_id = ?, current_status = ?, last_sync_source = ?, updated_at = ?
                WHERE card_id = ?
                """,
                (new_list_id, new_status, 'trello', datetime.now(), card_id)
            )
            conn.commit()

            # Get updated record
            cursor.execute("SELECT * FROM lead_card_mapping WHERE card_id = ?", (card_id,))
            record = cursor.fetchone()
            
            if record:
                updated = dict(record)
                logger.info(f"Updated Trello move in DB: Card {card_id} → Status {new_status}")
                return (True, updated)
            else:
                logger.warning(f"Card not found in DB: {card_id}")
                return (False, None)

        except sqlite3.Error as e:
            logger.error(f"Failed to update from Trello move: {str(e)}")
            return (False, None)
        finally:
            if conn:
                conn.close()

    def get_record_by_email(self, email: str) -> Optional[Dict]:
        """
        Get record by lead email
        
        Returns:
            Record dict or None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM lead_card_mapping WHERE lead_email = ?", (email,))
            row = cursor.fetchone()

            return dict(row) if row else None

        except sqlite3.Error as e:
            logger.error(f"Failed to get record by email: {str(e)}")
            return None
        finally:
            if conn:
                conn.close()

    def get_record_by_card_id(self, card_id: str) -> Optional[Dict]:
        """
        Get record by card ID
        
        Returns:
            Record dict or None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM lead_card_mapping WHERE card_id = ?", (card_id,))
            row = cursor.fetchone()

            return dict(row) if row else None

        except sqlite3.Error as e:
            logger.error(f"Failed to get record by card_id: {str(e)}")
            return None
        finally:
            if conn:
                conn.close()
        """
        Clear all data from database (for testing)

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM lead_card_mapping")
            cursor.execute("DELETE FROM sync_history")
            cursor.execute("DELETE FROM status_mapping")

            conn.commit()
            logger.info("Database cleared")
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to clear database: {str(e)}")
            return False

        finally:
            if conn:
                conn.close()
