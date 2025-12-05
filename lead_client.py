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

    def update_lead_status(self, lead_id: str, new_status: str) -> bool:
        """
        Update lead status in Google Sheets

        Args:
            lead_id: Lead ID (generated from Name+Email)
            new_status: New status value (New, Contacted, Qualified, Closed)

        Returns:
            True if successful, False otherwise
        """
        try:
            self._get_worksheet()
            
            # Get headers to find Status column
            headers = self._retry_on_rate_limit(self.worksheet.row_values, HEADER_ROW)
            status_column = None
            
            for idx, header in enumerate(headers, start=1):
                if header.lower() == "status":
                    status_column = idx
                    break
            
            if not status_column:
                logger.error(
                    f"Status column not found in headers",
                    extra={"extra_data": {"headers": headers}},
                )
                return False

            records = self._retry_on_rate_limit(self.worksheet.get_all_records)

            for idx, record in enumerate(records, start=2):  # Start at 2 (skip header)
                # Match by Name+Email ID
                record_id = str(record.get("Name", "") + "_" + record.get("Email", ""))[:20]
                if record_id == str(lead_id):
                    self._retry_on_rate_limit(
                        self.worksheet.update_cell, idx, status_column, new_status
                    )
                    logger.info(
                        f"Updated lead {lead_id} status to {new_status}",
                        extra={"extra_data": {"lead_id": lead_id, "status": new_status}},
                    )
                    return True

            logger.warning(
                f"Lead not found: {lead_id}",
                extra={"extra_data": {"lead_id": lead_id}},
            )
            return False

        except Exception as e:
            logger.error(
                f"Failed to update lead: {str(e)}",
                extra={"extra_data": {"lead_id": lead_id, "error": str(e)}},
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
