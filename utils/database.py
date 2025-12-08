"""
SQLAlchemy ORM-based database for lead-to-card mapping and sync tracking
Provides persistent storage for relationship between Google Sheets leads and Trello cards
"""

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from typing import Optional, List, Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)

DB_PATH = "sqlite:///sync_mapping.db"
engine = create_engine(DB_PATH, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================================================
# ORM Models
# ============================================================================

class LeadCardMapping(Base):
    """Lead-Card mapping table (central authority)"""
    __tablename__ = "lead_card_mapping"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(String(50), unique=True, nullable=False, index=True)
    lead_name = Column(String(255), nullable=False)
    lead_email = Column(String(255), nullable=False, index=True)
    lead_phone = Column(String(20), nullable=True)
    lead_company = Column(String(255), nullable=True)
    card_id = Column(String(100), unique=True, nullable=False, index=True)
    card_title = Column(String(255), nullable=False)
    trello_list_id = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="New")  # Current status: New, Contacted, Qualified, Closed
    current_status = Column(String(50), nullable=False, default="New")
    last_synced_status = Column(String(50), nullable=True)
    last_sync_source = Column(String(20), nullable=True)  # 'sheets' or 'trello'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "lead_name": self.lead_name,
            "lead_email": self.lead_email,
            "lead_phone": self.lead_phone,
            "lead_company": self.lead_company,
            "card_id": self.card_id,
            "card_title": self.card_title,
            "trello_list_id": self.trello_list_id,
            "status": self.status,
            "current_status": self.current_status,
            "last_synced_status": self.last_synced_status,
            "last_sync_source": self.last_sync_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SyncHistory(Base):
    """Sync history tracking table"""
    __tablename__ = "sync_history"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(String(50), nullable=True, index=True)
    card_id = Column(String(100), nullable=True, index=True)
    action = Column(String(20), nullable=False)  # 'create', 'update', 'delete', 'move'
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=True)
    source = Column(String(20), nullable=False)  # 'sheets' or 'trello'
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "card_id": self.card_id,
            "action": self.action,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "source": self.source,
            "success": self.success,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class StatusMapping(Base):
    """Status mapping configuration table"""
    __tablename__ = "status_mapping"

    id = Column(Integer, primary_key=True, index=True)
    sheet_status = Column(String(50), unique=True, nullable=False, index=True)
    trello_list_id = Column(String(100), nullable=False)
    trello_list_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "sheet_status": self.sheet_status,
            "trello_list_id": self.trello_list_id,
            "trello_list_name": self.trello_list_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# Database Initialization
# ============================================================================

def init_db():
    """Create all tables"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {str(e)}")
        raise


def get_db() -> Session:
    """Get database session - dependency for FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# SyncDatabase Class - High-level API
# ============================================================================

class SyncDatabase:
    """Database operations for lead-card sync"""

    def __init__(self, db: Session = None):
        """Initialize with optional session (for dependency injection)"""
        self.db = db

    def _get_session(self) -> Session:
        """Get a session if not provided"""
        if self.db:
            return self.db
        return SessionLocal()

    # ========== LeadCardMapping Operations ==========

    def get_mapping_by_lead_id(self, lead_id: str) -> Optional[Dict]:
        """Get card mapping for a lead"""
        db = self._get_session()
        try:
            record = db.query(LeadCardMapping).filter(LeadCardMapping.lead_id == lead_id).first()
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"Failed to get mapping by lead_id: {str(e)}")
            return None
        finally:
            if not self.db:
                db.close()

    def get_record_by_card_id(self, card_id: str) -> Optional[Dict]:
        """Get record by card ID"""
        db = self._get_session()
        try:
            record = db.query(LeadCardMapping).filter(LeadCardMapping.card_id == card_id).first()
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"Failed to get record by card_id: {str(e)}")
            return None
        finally:
            if not self.db:
                db.close()

    def get_record_by_email(self, email: str) -> Optional[Dict]:
        """Get record by lead email"""
        db = self._get_session()
        try:
            record = db.query(LeadCardMapping).filter(LeadCardMapping.lead_email == email).first()
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"Failed to get record by email: {str(e)}")
            return None
        finally:
            if not self.db:
                db.close()

    def get_all_mappings(self) -> List[Dict]:
        """Get all lead-card mappings"""
        db = self._get_session()
        try:
            records = db.query(LeadCardMapping).all()
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"Failed to get mappings: {str(e)}")
            return []
        finally:
            if not self.db:
                db.close()

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
        db = self._get_session()
        try:
            existing = db.query(LeadCardMapping).filter(LeadCardMapping.lead_id == lead_id).first()

            if existing:
                # Update existing record
                existing.lead_name = lead_name
                existing.lead_email = lead_email
                existing.lead_phone = lead_phone
                existing.lead_company = lead_company
                existing.status = current_status
                existing.current_status = current_status
                existing.last_sync_source = 'sheets'
                existing.updated_at = datetime.utcnow()
                db.commit()
                
                print(f"✓ Updated existing record: {lead_id}")
                logger.info(f"Updated record from Sheets: {lead_id}")
                return (True, 'updated', existing.to_dict())
            else:
                # Create new record with pending card_id
                pending_card_id = f"PENDING_{lead_id}"
                new_record = LeadCardMapping(
                    lead_id=lead_id,
                    lead_name=lead_name,
                    lead_email=lead_email,
                    lead_phone=lead_phone,
                    lead_company=lead_company,
                    card_id=pending_card_id,
                    card_title=f'{lead_name} (pending)',
                    trello_list_id='PENDING',
                    status=current_status,
                    current_status=current_status,
                    last_sync_source='sheets',
                    updated_at=datetime.utcnow()
                )
                db.add(new_record)
                db.commit()
                db.refresh(new_record)
                
                print(f"✓ Created new record: {lead_id}")
                logger.info(f"Created new record from Sheets: {lead_id}")
                return (True, 'created', new_record.to_dict())

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to upsert record from sheets: {str(e)}")
            print(f"✗ Database error: {str(e)}")
            return (False, 'error', None)
        finally:
            if not self.db:
                db.close()

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
        Create or update a record with actual Trello card info
        
        Returns:
            (success, record)
        """
        db = self._get_session()
        try:
            existing = db.query(LeadCardMapping).filter(LeadCardMapping.lead_id == lead_id).first()

            if existing:
                # Update existing record with card info
                existing.card_id = card_id
                existing.card_title = card_title
                existing.trello_list_id = trello_list_id
                existing.status = current_status
                existing.current_status = current_status
                existing.last_sync_source = 'sheets'
                existing.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
                logger.info(f"Updated record with card: {lead_id} → {card_id}")
                return (True, existing.to_dict())
            else:
                # Create new record
                new_record = LeadCardMapping(
                    lead_id=lead_id,
                    lead_name=lead_name,
                    lead_email=lead_email,
                    lead_phone=lead_phone,
                    lead_company=lead_company,
                    card_id=card_id,
                    card_title=card_title,
                    trello_list_id=trello_list_id,
                    status=current_status,
                    current_status=current_status,
                    last_sync_source='sheets',
                    updated_at=datetime.utcnow()
                )
                db.add(new_record)
                db.commit()
                db.refresh(new_record)
                logger.info(f"Created new record with card: {lead_id} → {card_id}")
                return (True, new_record.to_dict())

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create record with card: {str(e)}")
            return (False, None)
        finally:
            if not self.db:
                db.close()

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
        db = self._get_session()
        try:
            record = db.query(LeadCardMapping).filter(LeadCardMapping.card_id == card_id).first()

            if not record:
                logger.warning(f"Card not found in DB: {card_id}")
                return (False, None)

            record.trello_list_id = new_list_id
            record.status = new_status
            record.current_status = new_status
            record.last_sync_source = 'trello'
            record.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(record)

            logger.info(f"Updated Trello move in DB: Card {card_id} → Status {new_status}")
            return (True, record.to_dict())

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update from Trello move: {str(e)}")
            return (False, None)
        finally:
            if not self.db:
                db.close()

    def delete_mapping(self, lead_id: str = None, card_id: str = None) -> bool:
        """Delete a mapping"""
        db = self._get_session()
        try:
            if lead_id:
                db.query(LeadCardMapping).filter(LeadCardMapping.lead_id == lead_id).delete()
            elif card_id:
                db.query(LeadCardMapping).filter(LeadCardMapping.card_id == card_id).delete()
            else:
                return False

            db.commit()
            logger.info(f"Deleted mapping: lead_id={lead_id}, card_id={card_id}")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete mapping: {str(e)}")
            return False
        finally:
            if not self.db:
                db.close()

    # ========== SyncHistory Operations ==========

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
        """Record sync action in history"""
        db = self._get_session()
        try:
            history = SyncHistory(
                lead_id=lead_id,
                card_id=card_id,
                action=action,
                old_status=old_status,
                new_status=new_status,
                source=source,
                success=success,
                error_message=error_message,
            )
            db.add(history)
            db.commit()
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to record sync history: {str(e)}")
            return False
        finally:
            if not self.db:
                db.close()

    def get_sync_history(self, limit: int = 100) -> List[Dict]:
        """Get recent sync history"""
        db = self._get_session()
        try:
            records = db.query(SyncHistory).order_by(SyncHistory.created_at.desc()).limit(limit).all()
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"Failed to get sync history: {str(e)}")
            return []
        finally:
            if not self.db:
                db.close()

    # ========== StatusMapping Operations ==========

    def set_status_mapping(self, sheet_status: str, trello_list_id: str, trello_list_name: str) -> bool:
        """Set mapping between sheet status and trello list"""
        db = self._get_session()
        try:
            existing = db.query(StatusMapping).filter(StatusMapping.sheet_status == sheet_status).first()

            if existing:
                existing.trello_list_id = trello_list_id
                existing.trello_list_name = trello_list_name
            else:
                new_mapping = StatusMapping(
                    sheet_status=sheet_status,
                    trello_list_id=trello_list_id,
                    trello_list_name=trello_list_name,
                )
                db.add(new_mapping)

            db.commit()
            logger.info(f"Set status mapping: {sheet_status} → {trello_list_name}")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to set status mapping: {str(e)}")
            return False
        finally:
            if not self.db:
                db.close()

    def get_status_mapping(self, sheet_status: str = None) -> Optional[Dict]:
        """Get status mapping for a sheet status"""
        db = self._get_session()
        try:
            if sheet_status:
                record = db.query(StatusMapping).filter(StatusMapping.sheet_status == sheet_status).first()
                return record.to_dict() if record else None
            return None

        except Exception as e:
            logger.error(f"Failed to get status mapping: {str(e)}")
            return None
        finally:
            if not self.db:
                db.close()

    def get_all_status_mappings(self) -> List[Dict]:
        """Get all status mappings"""
        db = self._get_session()
        try:
            records = db.query(StatusMapping).all()
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"Failed to get status mappings: {str(e)}")
            return []
        finally:
            if not self.db:
                db.close()

    # ========== Utility Operations ==========

    def clear_all(self) -> bool:
        """Clear all data from database (for testing)"""
        db = self._get_session()
        try:
            db.query(SyncHistory).delete()
            db.query(LeadCardMapping).delete()
            db.query(StatusMapping).delete()
            db.commit()
            logger.info("Database cleared")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to clear database: {str(e)}")
            return False
        finally:
            if not self.db:
                db.close()
