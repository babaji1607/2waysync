"""
SIMPLE 2-WAY SYNC ENGINE
-----------------------
Simple, reliable cross-checking sync that properly handles:
1. Sheet → Trello: Create cards for leads without cards
2. Trello → Sheet: Update lead status when card moves to different list
"""

from typing import List, Dict, Optional
from datetime import datetime
from lead_client import LeadClient
from task_client import TaskClient
from utils.logger import setup_logger
from utils.models import Lead, Task
from utils.database import SyncDatabase
from utils.config import Config

logger = setup_logger(__name__)


class SimpleSyncEngine:
    """Simple 2-way sync with proper cross-checking"""

    def __init__(self):
        self.lead_client = LeadClient()
        self.task_client = TaskClient()
        self.db = SyncDatabase()
        self.stats = {
            "leads_checked": 0,
            "cards_created": 0,
            "statuses_updated": 0,
            "errors": 0,
        }

    def _map_status_to_list_id(self, sheet_status: str) -> Optional[str]:
        """Map Google Sheets status to Trello list ID"""
        mapping = {
            "New": Config.TRELLO_NEW_LIST_ID,
            "Contacted": Config.TRELLO_IN_PROGRESS_LIST_ID,
            "Qualified": Config.TRELLO_QUALIFIED_LIST_ID,
            "Closed": Config.TRELLO_DONE_LIST_ID,
            "Completed": Config.TRELLO_DONE_LIST_ID,  # Treat "Completed" as "Closed"
        }
        return mapping.get(sheet_status)

    def _map_list_id_to_status(self, list_id: str) -> str:
        """Map Trello list ID back to Google Sheets status"""
        reverse_mapping = {
            Config.TRELLO_NEW_LIST_ID: "New",
            Config.TRELLO_IN_PROGRESS_LIST_ID: "Contacted",
            Config.TRELLO_QUALIFIED_LIST_ID: "Qualified",
            Config.TRELLO_DONE_LIST_ID: "Closed",
        }
        return reverse_mapping.get(list_id, "New")

    def sync(self):
        """
        Execute 2-way sync with proper cross-checking
        
        Phase 1: Google Sheets → Trello
          - For each lead in sheet: check if card exists
          - If not: CREATE card in correct list based on status
          - If yes: check if status matches, update if needed
          
        Phase 2: Trello → Google Sheets  
          - For each card in Trello: check if lead exists in sheet
          - If not: SKIP (card was created manually)
          - If yes: check if card is in correct list
          - If list changed: UPDATE lead status in sheet
        """
        logger.info("=" * 70)
        logger.info("STARTING 2-WAY SYNC")
        logger.info("=" * 70)

        # Reset stats
        self.stats = {
            "leads_checked": 0,
            "cards_created": 0,
            "statuses_updated": 0,
            "errors": 0,
        }

        try:
            # Fetch all data
            logger.info("Phase 1: Fetching data from Google Sheets and Trello...")
            leads = self.lead_client.get_all_leads()
            cards = self.task_client.get_all_tasks()
            
            logger.info(f"  - Found {len(leads)} leads in Google Sheets")
            logger.info(f"  - Found {len(cards)} cards in Trello")

            # PHASE 1: SHEETS -> TRELLO
            logger.info("\nPhase 2: Syncing Google Sheets leads to Trello cards...")
            self._sync_sheets_to_trello(leads, cards)

            # PHASE 2: TRELLO -> SHEETS
            logger.info("\nPhase 3: Syncing Trello cards back to Google Sheets...")
            self._sync_trello_to_sheets(leads, cards)

            # Log summary
            logger.info("\n" + "=" * 70)
            logger.info("SYNC COMPLETE")
            logger.info(f"  - Leads checked: {self.stats['leads_checked']}")
            logger.info(f"  - Cards created: {self.stats['cards_created']}")
            logger.info(f"  - Statuses updated: {self.stats['statuses_updated']}")
            logger.info(f"  - Errors: {self.stats['errors']}")
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"CRITICAL SYNC ERROR: {str(e)}")
            self.stats["errors"] += 1

    def _sync_sheets_to_trello(self, leads: List[Lead], cards: List[Task]):
        """
        Phase 1: Sync Google Sheets leads to Trello
        For each lead: check if card exists, create if not, update if needed
        """
        for lead in leads:
            self.stats["leads_checked"] += 1
            
            try:
                # Look up existing mapping in database
                mapping = self.db.get_mapping_by_lead_id(lead.id)
                card_id = mapping.get("card_id") if mapping else None

                # Check if card still exists in Trello
                card = next((c for c in cards if c.id == card_id), None) if card_id else None

                if card:
                    # Card exists - check if status needs update
                    current_list_id = card.list_id
                    expected_list_id = self._map_status_to_list_id(lead.status)

                    if current_list_id != expected_list_id:
                        # Status changed - move card to new list
                        logger.info(
                            f"STATUS UPDATE: Moving card for '{lead.name}' from list {current_list_id} to {expected_list_id}"
                        )
                        new_status = self._map_list_id_to_status(expected_list_id)
                        success = self.task_client.update_task(
                            card_id,
                            status=new_status,
                            title=f"{lead.name} ({lead.email})" if lead.email else lead.name,
                            notes=self._format_card_description(lead),
                        )
                        if success:
                            self.stats["statuses_updated"] += 1
                            self.db.add_sync_history(
                                action="update_status",
                                lead_id=lead.id,
                                card_id=card_id,
                                old_status=card.status,
                                new_status=new_status,
                                source="sheets",
                                success=True,
                            )
                    else:
                        logger.info(f"UNCHANGED: Card for '{lead.name}' status matches (status: {lead.status})")
                else:
                    # Card doesn't exist - CREATE IT
                    target_list_id = self._map_status_to_list_id(lead.status)
                    if not target_list_id:
                        logger.error(
                            f"SKIP: Cannot map status '{lead.status}' for lead '{lead.name}' - no list configured"
                        )
                        self.stats["errors"] += 1
                        continue

                    logger.info(
                        f"CREATE CARD: '{lead.name}' ({lead.email}) with status '{lead.status}' in list {target_list_id}"
                    )

                    card_id = self.task_client.create_task_in_list(
                        list_id=target_list_id,
                        title=f"{lead.name} ({lead.email})" if lead.email else lead.name,
                        description=self._format_card_description(lead),
                    )

                    if card_id:
                        # Update database mapping
                        self.db.add_mapping(
                            lead_id=lead.id,
                            lead_name=lead.name,
                            lead_email=lead.email,
                            card_id=card_id,
                            card_title=f"{lead.name} ({lead.email})" if lead.email else lead.name,
                            trello_list_id=target_list_id,
                            status=lead.status,
                        )
                        self.db.add_sync_history(
                            action="create",
                            lead_id=lead.id,
                            card_id=card_id,
                            new_status=lead.status,
                            source="sheets",
                            success=True,
                        )
                        self.stats["cards_created"] += 1
                        logger.info(f"  SUCCESS: Created card {card_id}")
                    else:
                        logger.error(f"  FAILED: Could not create card for '{lead.name}'")
                        self.stats["errors"] += 1
                        self.db.add_sync_history(
                            action="create",
                            lead_id=lead.id,
                            new_status=lead.status,
                            source="sheets",
                            success=False,
                            error_message="Failed to create card",
                        )

            except Exception as e:
                logger.error(f"ERROR syncing lead '{lead.name}': {str(e)}")
                self.stats["errors"] += 1

    def _sync_trello_to_sheets(self, leads: List[Lead], cards: List[Task]):
        """
        Phase 2: Sync Trello card changes back to Google Sheets
        For each card: if it has a mapping, check if status matches
        """
        for card in cards:
            try:
                # Look up mapping by card ID
                mapping = self.db.get_mapping_by_card_id(card.id)
                if not mapping:
                    logger.info(f"SKIPPING: Card '{card.title}' has no lead mapping (manual card)")
                    continue

                lead_id = mapping.get("lead_id")
                lead = next((l for l in leads if l.id == lead_id), None)

                if not lead:
                    logger.warning(f"WARNING: Card '{card.title}' mapped to lead {lead_id} but lead not found in sheet")
                    continue

                # Check if card is in correct list for lead's status
                expected_list_id = self._map_status_to_list_id(lead.status)
                if card.list_id != expected_list_id:
                    # Card was moved to different list - update sheet status
                    new_status = self._map_list_id_to_status(card.list_id)
                    logger.info(
                        f"STATUS UPDATE: Card '{card.title}' moved to list {card.list_id} - updating lead '{lead.name}' to '{new_status}'"
                    )

                    success = self.lead_client.update_lead_status(lead.id, new_status)
                    if success:
                        self.stats["statuses_updated"] += 1
                        self.db.add_sync_history(
                            action="update_status",
                            lead_id=lead_id,
                            card_id=card.id,
                            old_status=lead.status,
                            new_status=new_status,
                            source="trello",
                            success=True,
                        )
                    else:
                        logger.error(f"  FAILED: Could not update status for '{lead.name}'")
                        self.stats["errors"] += 1
                else:
                    logger.info(f"UNCHANGED: Card '{card.title}' in correct list (status: {lead.status})")

            except Exception as e:
                logger.error(f"ERROR syncing card '{card.title}': {str(e)}")
                self.stats["errors"] += 1

    def _format_card_description(self, lead: Lead) -> str:
        """Format lead info for card description"""
        return f"""Lead ID: {lead.id}
Email: {lead.email or 'N/A'}
Phone: {lead.phone or 'N/A'}
Company: {lead.company or 'N/A'}
Status: {lead.status}"""


def run_sync():
    """Run the sync"""
    engine = SimpleSyncEngine()
    engine.sync()


if __name__ == "__main__":
    run_sync()
