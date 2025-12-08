import gspread
import os
import time
from typing import List, Optional
from oauth2client.service_account import ServiceAccountCredentials
from utils.logger import setup_logger
from utils.models import Lead, LeadStatus
from utils.config import Config

logger = setup_logger(__name__)

# Scopes for Google Sheets API
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER_ROW = 1  # First row contains headers


class LeadClient:
    """Google Sheets Lead Tracker client"""

    def __init__(self, credentials_path: str = None):
        """
        Initialize Google Sheets client

        Args:
            credentials_path: Path to Google service account credentials JSON
        """
        # Load from Config if not provided (runtime loading)
        self.credentials_path = credentials_path or Config.GOOGLE_CREDENTIALS_JSON
        self.sheet_id = Config.GOOGLE_SHEETS_ID
        self.client = None
        self.worksheet = None
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate with Google Sheets API"""
        try:
            if not os.path.exists(self.credentials_path):
                logger.warning(
                    f"Credentials file not found: {self.credentials_path}. Running in demo mode.",
                    extra={"extra_data": {"file": self.credentials_path}},
                )
                self.client = None
                return
            
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                self.credentials_path, SCOPES
            )
            self.client = gspread.authorize(creds)
            logger.info("Successfully authenticated with Google Sheets")
        except FileNotFoundError:
            logger.warning(
                f"Credentials file not found: {self.credentials_path}. Running in demo mode.",
                extra={"extra_data": {"file": self.credentials_path}},
            )
            self.client = None
        except Exception as e:
            logger.error(
                f"Failed to authenticate with Google Sheets: {str(e)}",
                extra={"extra_data": {"error": str(e)}},
            )
            self.client = None

    def _get_worksheet(self) -> None:
        """Get or open worksheet"""
        try:
            if not self.worksheet:
                spreadsheet = self.client.open_by_key(self.sheet_id)
                self.worksheet = spreadsheet.sheet1
                logger.info("Opened Google Sheet successfully")
        except Exception as e:
            logger.error(
                f"Failed to open worksheet: {str(e)}",
                extra={"extra_data": {"error": str(e), "sheet_id": self.sheet_id}},
            )
            raise

    def _retry_on_rate_limit(self, func, *args, max_retries=3, **kwargs):
        """Retry function on rate limit with exponential backoff"""
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"Rate limit hit, retrying in {wait_time}s",
                        extra={"extra_data": {"attempt": attempt, "wait_time": wait_time}},
                    )
                    time.sleep(wait_time)
                else:
                    raise
        raise Exception("Max retries exceeded")

    def add_lead(self, name: str, email: str, phone: str = "", status: str = "NEW", source: str = "", notes: str = "") -> Optional[str]:
        """
        Add a new lead to Google Sheets

        Args:
            name: Lead name
            email: Lead email
            phone: Lead phone
            status: Lead status
            source: Lead source
            notes: Lead notes

        Returns:
            Lead ID if successful, None otherwise
        """
        try:
            if not self.client:
                logger.warning("No Google Sheets client - cannot add lead")
                return None
            
            self._get_worksheet()
            
            # Generate a simple ID (timestamp-based or UUID)
            import uuid
            lead_id = str(uuid.uuid4())[:8]
            
            # Append new row
            new_row = [lead_id, name, email, phone, status, "", source, notes]
            self._retry_on_rate_limit(self.worksheet.append_row, new_row)
            
            logger.info(
                f"Added new lead {lead_id} ({name}, {email})",
                extra={"extra_data": {"lead_id": lead_id, "name": name, "email": email}},
            )
            return lead_id
            
        except Exception as e:
            logger.error(
                f"Failed to add lead: {str(e)}",
                extra={"extra_data": {"name": name, "email": email, "error": str(e)}},
            )
            return None

    def get_lead_by_email(self, email: str) -> Optional[Lead]:
        """
        Get a lead by email

        Args:
            email: Lead email

        Returns:
            Lead object if found, None otherwise
        """
        try:
            leads = self.get_all_leads()
            for lead in leads:
                if lead.email.lower() == email.lower():
                    return lead
            return None
        except Exception as e:
            logger.error(
                f"Failed to get lead by email: {str(e)}",
                extra={"extra_data": {"email": email, "error": str(e)}},
            )
            return None

    def get_all_leads(self) -> List[Lead]:
        """
        Fetch all leads from Google Sheets

        Returns:
            List of Lead objects (excluding LOST status)
        """
        try:
            if not self.client:
                logger.warning("No Google Sheets client - returning demo data")
                return [
                    Lead(id="DEMO1", name="Demo Lead 1", email="demo1@example.com", status="NEW"),
                    Lead(id="DEMO2", name="Demo Lead 2", email="demo2@example.com", status="CONTACTED"),
                ]
            
            self._get_worksheet()
            records = self._retry_on_rate_limit(self.worksheet.get_all_records)

            leads = []
            for record in records:
                try:
                    # Map Google Sheets columns: Name, Email, Phone, Company, Status, Notes
                    status = record.get("Status", "New")
                    
                    lead = Lead(
                        id=str(record.get("Name", "") + "_" + record.get("Email", ""))[:20],  # Generate ID from name+email
                        name=record.get("Name", ""),
                        email=record.get("Email", ""),
                        phone=record.get("Phone", ""),
                        company=record.get("Company", ""),
                        status=status,
                        notes=record.get("Notes", ""),
                        trello_card_id=record.get("trello_card_id"),
                    )
                    leads.append(lead)
                except Exception as e:
                    logger.error(
                        f"Failed to parse lead record: {str(e)}",
                        extra={"extra_data": {"record": record, "error": str(e)}},
                    )
                    continue

            logger.info(
                f"Fetched {len(leads)} leads from Google Sheets",
                extra={"extra_data": {"count": len(leads)}},
            )
            return leads

        except Exception as e:
            logger.error(
                f"Failed to fetch leads: {str(e)}",
                extra={"extra_data": {"error": str(e)}},
            )
            return []

    def update_lead_status(self, lead_id: str, new_status: str, lead_name: str = None, lead_email: str = None) -> bool:
        """
        Update lead status in Google Sheets

        Args:
            lead_id: Lead ID (can be Name_Email or numeric ID)
            new_status: New status value (New, Contacted, Qualified, Closed)
            lead_name: Optional lead name for additional lookup method
            lead_email: Optional lead email for additional lookup method

        Returns:
            True if successful, False otherwise
        """
        try:
            self._get_worksheet()
            
            # Get headers to find Status column
            headers = self._retry_on_rate_limit(self.worksheet.row_values, HEADER_ROW)
            logger.info(
                f"Headers found: {headers}",
                extra={"extra_data": {"headers": headers}},
            )
            
            status_column = None
            
            # Look for status column (case-insensitive)
            for idx, header in enumerate(headers, start=1):
                if header.lower().strip() == "status":
                    status_column = idx
                    break
            
            if not status_column:
                logger.error(
                    f"Status column not found in headers",
                    extra={"extra_data": {"headers": headers}},
                )
                return False
            
            logger.info(f"Status column found at index: {status_column}")

            records = self._retry_on_rate_limit(self.worksheet.get_all_records)
            logger.info(
                f"Total records in sheet: {len(records)}",
                extra={"extra_data": {"record_count": len(records)}},
            )

            for idx, record in enumerate(records, start=2):  # Start at 2 (skip header)
                # Get record details - try both lowercase and capitalized column names
                record_name = record.get("name", record.get("Name", ""))
                record_email = record.get("email", record.get("Email", ""))
                record_id = record.get("id", record.get("ID", ""))
                
                logger.debug(
                    f"Checking record {idx}: id={record_id}, name={record_name}, email={record_email}",
                    extra={"extra_data": {"row": idx, "id": record_id, "name": record_name, "email": record_email}},
                )
                
                # Method 1: Try matching by id column (convert both to string for comparison)
                if str(record_id).strip() and str(record_id).strip() == str(lead_id).strip():
                    logger.info(f"✓ Match found using Method 1 (id column) at row {idx}")
                    self._retry_on_rate_limit(
                        self.worksheet.update_cell, idx, status_column, new_status
                    )
                    logger.info(
                        f"✓ Updated lead {lead_id} status to {new_status}",
                        extra={"extra_data": {"lead_id": lead_id, "status": new_status, "method": "id_column", "row": idx}},
                    )
                    return True
                
                # Method 2: Try matching by name+email format (Name_Email)
                if record_name and record_email:
                    generated_record_id = str(record_name + "_" + record_email)[:20].strip()
                    generated_lead_id = str(lead_id)[:20].strip()
                    
                    logger.debug(
                        f"Comparing generated IDs - Record: '{generated_record_id}' vs Lead: '{generated_lead_id}'",
                        extra={"extra_data": {"generated_record_id": generated_record_id, "generated_lead_id": generated_lead_id}},
                    )
                    
                    if generated_record_id == generated_lead_id:
                        logger.info(f"✓ Match found using Method 2 (name+email) at row {idx}")
                        self._retry_on_rate_limit(
                            self.worksheet.update_cell, idx, status_column, new_status
                        )
                        logger.info(
                            f"✓ Updated lead {lead_id} status to {new_status}",
                            extra={"extra_data": {"lead_id": lead_id, "status": new_status, "method": "name_email", "row": idx}},
                        )
                        return True
                
                # Method 3: If name and email provided, try direct match
                if lead_name and lead_email:
                    name_match = record_name.strip().lower() == lead_name.strip().lower()
                    email_match = record_email.strip().lower() == lead_email.strip().lower()
                    
                    if name_match and email_match:
                        logger.info(f"✓ Match found using Method 3 (direct name+email match) at row {idx}")
                        self._retry_on_rate_limit(
                            self.worksheet.update_cell, idx, status_column, new_status
                        )
                        logger.info(
                            f"✓ Updated lead {lead_id} status to {new_status}",
                            extra={"extra_data": {"lead_id": lead_id, "status": new_status, "method": "direct_match", "row": idx}},
                        )
                        return True

            logger.warning(
                f"✗ Lead not found in any records",
                extra={"extra_data": {
                    "lead_id": lead_id, 
                    "lead_name": lead_name, 
                    "lead_email": lead_email, 
                    "total_records": len(records),
                    "searched_methods": ["id_column", "name_email_format", "direct_match"]
                }},
            )
            return False

        except Exception as e:
            logger.error(
                f"Failed to update lead: {str(e)}",
                extra={"extra_data": {"lead_id": lead_id, "error": str(e), "error_type": type(e).__name__}},
            )
            return False

    def update_trello_task_id(self, lead_id: str, trello_task_id: str) -> bool:
        """
        Store Trello task ID in lead record for idempotency

        Args:
            lead_id: Lead ID
            trello_task_id: Trello task ID

        Returns:
            True if successful, False otherwise
        """
        try:
            self._get_worksheet()
            records = self._retry_on_rate_limit(self.worksheet.get_all_records)

            for idx, record in enumerate(records, start=2):
                if str(record.get("id")) == str(lead_id):
                    self._retry_on_rate_limit(
                        self.worksheet.update_cell,
                        idx,
                        6,
                        trello_task_id,
                    )  # Column 6 for trello_task_id
                    logger.info(
                        f"Stored Trello task ID for lead {lead_id}",
                        extra={"extra_data": {"lead_id": lead_id, "task_id": trello_task_id}},
                    )
                    return True

            return False

        except Exception as e:
            logger.error(
                f"Failed to update Trello task ID: {str(e)}",
                extra={"extra_data": {"lead_id": lead_id, "error": str(e)}},
            )
            return False
