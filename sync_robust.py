"""
Robust 2-way sync engine with database as central authority
Database is the source of truth for all sync decisions
"""

from typing import List, Optional
from utils.logger import setup_logger
from utils.models import Lead, Task
from lead_client import LeadClient
from task_client import TaskClient
from utils.database import SyncDatabase
from utils.config import Config

logger = setup_logger(__name__)


class RobustSyncEngine:
    """Sync engine with database as central authority"""

    def __init__(self):
        """Initialize sync engine"""
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
        # Normalize status to title case
        normalized_status = sheet_status.strip().title() if sheet_status else "New"
        mapping = {
            "New": Config.TRELLO_NEW_LIST_ID,
            "Contacted": Config.TRELLO_IN_PROGRESS_LIST_ID,
            "Qualified": Config.TRELLO_QUALIFIED_LIST_ID,
            "Closed": Config.TRELLO_DONE_LIST_ID,
        }
        return mapping.get(normalized_status)

    def _map_list_id_to_status(self, list_id: str) -> str:
        """Map Trello list ID to Google Sheets status"""
        reverse_mapping = {
            Config.TRELLO_NEW_LIST_ID: "New",
            Config.TRELLO_IN_PROGRESS_LIST_ID: "Contacted",
            Config.TRELLO_QUALIFIED_LIST_ID: "Qualified",
            Config.TRELLO_DONE_LIST_ID: "Closed",
        }
        return reverse_mapping.get(list_id, "New")

    def _format_card_description_for_new_card(self, lead_id, lead_name, lead_email, lead_phone, lead_company, status):
        """Format card description with lead info and lead_id"""
        description = f"""Lead ID: {lead_id}
Name: {lead_name}
Email: {lead_email or 'N/A'}
Phone: {lead_phone or 'N/A'}
Company: {lead_company or 'N/A'}
Status: {status}
Source: Google Sheets"""
        return description

    def sync_from_sheets_webhook(self, lead_data: dict) -> dict:
        """
        Handle sync when data received from Google Sheets webhook
        Database is central authority
        
        Process:
        1. If record exists in DB -> update it
        2. If record doesn't exist -> store for later card creation
        3. Check Trello for existing card
        4. If Trello card exists and DB has it -> check list, update if needed
        5. If Trello card doesn't exist in DB -> create it
        
        Returns:
            Result dict with actions taken
        """
        print("\n" + "=" * 70)
        print("SYNC FROM GOOGLE SHEETS")
        print("=" * 70)
        
        try:
            lead_id = lead_data.get("lead_id", "")
            lead_name = lead_data.get("lead_name", "")
            lead_email = lead_data.get("lead_email", "")
            lead_phone = lead_data.get("lead_phone", "")
            lead_company = lead_data.get("lead_company", "")
            sheet_status = lead_data.get("status", "New")

            if not lead_name:
                print("ERROR: Missing lead_name")
                return {"success": False, "error": "Missing lead_name"}

            # Generate lead_id from Name+Email if not provided
            if not lead_id:
                lead_id = str(f"{lead_name}_{lead_email}")[:20]
                print(f"Generated lead_id from Name+Email: {lead_id}")

            print(f"Lead ID: {lead_id}")
            print(f"Name: {lead_name}")
            print(f"Email: {lead_email}")
            print(f"Status: {sheet_status}")

            # Step 1: Upsert record in database
            db_updated, action, db_record = self.db.upsert_record_from_sheets(
                lead_id, lead_name, lead_email, lead_phone, lead_company, sheet_status
            )

            if action == 'updated':
                print(f"✓ Database record updated: {lead_id}")
                
                # Step 2: Check if card exists in DB and Trello
                # Card exists if card_id doesn't start with 'PENDING_'
                card_id = db_record.get("card_id")
                if card_id and not card_id.startswith("PENDING_"):
                    print(f"  Card exists: {card_id}")
                    
                    # Check if card is in correct list
                    expected_list_id = self._map_status_to_list_id(sheet_status)
                    current_list_id = db_record.get("trello_list_id")
                    
                    if current_list_id != expected_list_id:
                        print(f"  Status mismatch: {current_list_id} != {expected_list_id}")
                        print(f"  Moving card to correct list...")
                        
                        # Move card in Trello
                        success = self.task_client.update_task(
                            card_id,
                            status=sheet_status,
                            title=f"{lead_name} ({lead_email})" if lead_email else lead_name
                        )
                        
                        if success:
                            # Update DB with new list ID
                            self.db.update_from_trello_move(card_id, expected_list_id, sheet_status)
                            print(f"  ✓ Card moved to correct list")
                            self.stats["statuses_updated"] += 1
                        else:
                            print(f"  ✗ Failed to move card")
                            self.stats["errors"] += 1
                    else:
                        print(f"  ✓ Card already in correct list")
                else:
                    # No card yet - will be created when syncing leads without cards
                    print(f"  No card yet - will be created in full sync")

            elif action == 'created':
                print(f"✓ New record created in DB: {lead_id}")
                
                # Step 2: Check if Trello card exists (might have been created manually)
                print(f"  Checking for existing Trello card...")
                try:
                    all_cards = self.task_client.get_all_tasks()
                    print(f"  Found {len(all_cards)} total cards in Trello")
                except Exception as e:
                    print(f"  ✗ Error fetching Trello cards: {str(e)}")
                    all_cards = []
                
                existing_card = None
                
                # Look for card by lead_id in description
                for card in all_cards:
                    card_desc = card.description or ""
                    if lead_id in card_desc:
                        existing_card = card
                        print(f"  ✓ Found matching card by lead_id in description")
                        break
                
                if existing_card:
                    # Card exists - update DB with card info
                    print(f"  ✓ Found existing card in Trello: {existing_card.id}")
                    self.db.create_record_with_card(
                        lead_id=lead_id,
                        lead_name=lead_name,
                        lead_email=lead_email,
                        lead_phone=lead_phone,
                        lead_company=lead_company,
                        card_id=existing_card.id,
                        card_title=existing_card.title,
                        trello_list_id=existing_card.list_id,
                        current_status=sheet_status
                    )
                    
                    # Check if card is in correct list
                    expected_list_id = self._map_status_to_list_id(sheet_status)
                    if existing_card.list_id != expected_list_id:
                        print(f"  Card in wrong list - moving to correct list...")
                        success = self.task_client.update_task(
                            existing_card.id,
                            status=sheet_status,
                            title=f"{lead_name} ({lead_email})" if lead_email else lead_name
                        )
                        if success:
                            self.db.update_from_trello_move(existing_card.id, expected_list_id, sheet_status)
                            print(f"  ✓ Card moved to correct list")
                            self.stats["statuses_updated"] += 1
                    else:
                        print(f"  ✓ Card already in correct list")
                else:
                    # No card exists - create one
                    print(f"  No card found - CREATING NEW CARD...")
                    target_list_id = self._map_status_to_list_id(sheet_status)
                    
                    if not target_list_id:
                        print(f"  ✗ Cannot map status {sheet_status} to list ID")
                        self.stats["errors"] += 1
                        return {"success": False, "error": f"Cannot map status {sheet_status} to Trello list"}
                    
                    card_title = f"{lead_name} ({lead_email})" if lead_email else lead_name
                    card_description = self._format_card_description_for_new_card(
                        lead_id, lead_name, lead_email, lead_phone, lead_company, sheet_status
                    )
                    
                    try:
                        card_id = self.task_client.create_task_in_list(
                            target_list_id,
                            card_title,
                            card_description
                        )
                    except Exception as e:
                        print(f"  ✗ Failed to create card: {str(e)}")
                        card_id = None
                    
                    if card_id:
                        print(f"  ✓ Card created: {card_id}")
                        self.db.create_record_with_card(
                            lead_id=lead_id,
                            lead_name=lead_name,
                            lead_email=lead_email,
                            lead_phone=lead_phone,
                            lead_company=lead_company,
                            card_id=card_id,
                            card_title=card_title,
                            trello_list_id=target_list_id,
                            current_status=sheet_status
                        )
                        self.stats["cards_created"] += 1
                    else:
                        print(f"  ✗ Card creation failed")
                        self.stats["errors"] += 1

            elif action == 'error':
                print(f"✗ Failed to upsert database record")
                self.stats["errors"] += 1
                return {"success": False, "error": "Database upsert failed"}

            print("-" * 70)
            print("✓ Google Sheets sync complete\n")
            return {"success": True, "action": action, "lead_id": lead_id}

        except Exception as e:
            logger.error(f"Error in sheets webhook sync: {str(e)}")
            print(f"✗ Error: {str(e)}\n")
            self.stats["errors"] += 1
            return {"success": False, "error": str(e)}

    def sync_from_trello_webhook(self, card_data: dict) -> dict:
        """
        Handle sync when data received from Trello webhook
        Database is central authority
        
        Process:
        1. Get card info from Trello webhook
        2. Check database for card ID
        3. If found in DB:
           - Update DB with new list ID and status
           - Update Google Sheets with new status
        4. If not found in DB:
           - Log warning (manual card created in Trello)
        
        Returns:
            Result dict with actions taken
        """
        print("\n" + "=" * 70)
        print("SYNC FROM TRELLO")
        print("=" * 70)
        
        try:
            card_id = card_data.get("card_id", "")
            card_name = card_data.get("card_name", "")
            new_list_id = card_data.get("list_id", "")
            action_type = card_data.get("action_type", "unknown")

            if not card_id:
                print("ERROR: Missing card_id")
                return {"success": False, "error": "Missing card_id"}

            print(f"Card ID: {card_id}")
            print(f"Card Name: {card_name}")
            print(f"Action: {action_type}")

            # Step 1: Check database for this card
            db_record = self.db.get_record_by_card_id(card_id)
            
            if not db_record:
                print(f"⚠ Card not found in database (manual card in Trello)")
                print("-" * 70 + "\n")
                return {"success": False, "error": "Card not in database"}

            print(f"✓ Found record in database: {db_record['lead_id']}")

            # Step 2: Determine new status from list ID
            new_status = self._map_list_id_to_status(new_list_id)
            current_status = db_record.get("current_status")
            last_sync_source = db_record.get("last_sync_source")

            if current_status != new_status:
                print(f"Status changed: {current_status} → {new_status}")
                
                # Skip if this is an echo from Sheets (just created/updated by us)
                if last_sync_source == "sheets":
                    print(f"  ℹ Skipping - this change originated from Sheets (echo prevention)")
                    return {"success": True, "echo_skipped": True}
                
                # Step 3: Update database with new list ID and status
                db_success, updated_record = self.db.update_from_trello_move(
                    card_id, new_list_id, new_status
                )
                
                if db_success:
                    print(f"✓ Database updated")
                    
                    # Step 4: Update Google Sheets with new status
                    lead_id = db_record["lead_id"]
                    sheet_updated = self.lead_client.update_lead_status(lead_id, new_status)
                    
                    if sheet_updated:
                        print(f"✓ Google Sheets updated: {new_status}")
                        self.stats["statuses_updated"] += 1
                    else:
                        print(f"✗ Failed to update Google Sheets")
                        self.stats["errors"] += 1
                else:
                    print(f"✗ Failed to update database")
                    self.stats["errors"] += 1
            else:
                print(f"✓ Status already correct: {current_status}")

            print("-" * 70)
            print("✓ Trello sync complete\n")
            return {"success": True, "status_updated": current_status != new_status}

        except Exception as e:
            logger.error(f"Error in Trello webhook sync: {str(e)}")
            print(f"✗ Error: {str(e)}\n")
            self.stats["errors"] += 1
            return {"success": False, "error": str(e)}

    def full_sync(self):
        """
        Full bi-directional sync
        Database is central authority for all decisions
        """
        print("\n" + "=" * 70)
        print("STARTING FULL BI-DIRECTIONAL SYNC")
        print("=" * 70)
        
        self.stats = {
            "leads_checked": 0,
            "cards_created": 0,
            "statuses_updated": 0,
            "errors": 0,
        }

        try:
            # Phase 1: Fetch all data
            print("\nPhase 1: Fetching data from Sheets and Trello...")
            leads = self.lead_client.get_all_leads()
            cards = self.task_client.get_all_tasks()
            
            print(f"  Leads from Sheets: {len(leads)}")
            print(f"  Cards from Trello: {len(cards)}")

            # Phase 2: Sheets → Trello (create missing cards)
            print("\nPhase 2: Syncing Sheets to Trello (create missing cards)...")
            self._create_missing_cards(leads, cards)

            # Phase 3: Trello → Sheets (update status from moves)
            print("\nPhase 3: Syncing Trello to Sheets (status updates)...")
            self._update_sheets_from_trello(cards)

            # Print summary
            print("\n" + "=" * 70)
            print("SYNC COMPLETE")
            print(f"  Leads checked: {self.stats['leads_checked']}")
            print(f"  Cards created: {self.stats['cards_created']}")
            print(f"  Statuses updated: {self.stats['statuses_updated']}")
            print(f"  Errors: {self.stats['errors']}")
            print("=" * 70 + "\n")

        except Exception as e:
            logger.error(f"Full sync error: {str(e)}")
            print(f"✗ Full sync error: {str(e)}\n")
            self.stats["errors"] += 1

    def _create_missing_cards(self, leads: List[Lead], cards: List[Task]):
        """Create cards for leads that don't have them"""
        for lead in leads:
            self.stats["leads_checked"] += 1
            
            try:
                # Check if card exists in DB
                db_record = self.db.get_mapping_by_lead_id(lead.id)
                
                if db_record and db_record.get("card_id"):
                    # Card exists, check Trello has it
                    card_id = db_record["card_id"]
                    card_exists = any(c.id == card_id for c in cards)
                    
                    if card_exists:
                        print(f"✓ {lead.name}: Card exists")
                    else:
                        print(f"⚠ {lead.name}: Card in DB but not in Trello (deleted?)")
                else:
                    # No card - create one
                    print(f"→ {lead.name}: Creating card...")
                    
                    target_list_id = self._map_status_to_list_id(lead.status)
                    card_title = f"{lead.name} ({lead.email})" if lead.email else lead.name
                    card_desc = self._format_card_description(lead)
                    
                    card_id = self.task_client.create_task_in_list(
                        target_list_id,
                        card_title,
                        card_desc
                    )
                    
                    if card_id:
                        # Save in DB
                        self.db.create_record_with_card(
                            lead_id=lead.id,
                            lead_name=lead.name,
                            lead_email=lead.email,
                            lead_phone=lead.phone,
                            lead_company=lead.company,
                            card_id=card_id,
                            card_title=f"{lead.name} ({lead.email})" if lead.email else lead.name,
                            trello_list_id=target_list_id,
                            current_status=lead.status
                        )
                        print(f"  ✓ Card created: {card_id}")
                        self.stats["cards_created"] += 1
                    else:
                        print(f"  ✗ Failed to create card")
                        self.stats["errors"] += 1

            except Exception as e:
                logger.error(f"Error creating card for {lead.name}: {str(e)}")
                self.stats["errors"] += 1

    def _update_sheets_from_trello(self, cards: List[Task]):
        """Update Sheets status based on Trello card positions"""
        for card in cards:
            try:
                # Check if card is in DB
                db_record = self.db.get_record_by_card_id(card.id)
                
                if not db_record:
                    print(f"⚠ {card.title}: Not in DB (manual card)")
                    continue

                # Check if list matches expected
                expected_list_id = self._map_status_to_list_id(db_record["current_status"])
                
                if card.list_id != expected_list_id:
                    # Card moved - update status
                    new_status = self._map_list_id_to_status(card.list_id)
                    print(f"→ {card.title}: Updating to {new_status}...")
                    
                    # Update DB
                    self.db.update_from_trello_move(card.id, card.list_id, new_status)
                    
                    # Update Sheet
                    lead_id = db_record["lead_id"]
                    updated = self.lead_client.update_lead_status(lead_id, new_status)
                    
                    if updated:
                        print(f"  ✓ Updated to {new_status}")
                        self.stats["statuses_updated"] += 1
                    else:
                        print(f"  ✗ Failed to update")
                        self.stats["errors"] += 1

            except Exception as e:
                logger.error(f"Error syncing card {card.id}: {str(e)}")
                self.stats["errors"] += 1

    def _format_card_description(self, lead: Lead) -> str:
        """Format lead info for card description"""
        return f"""Lead ID: {lead.id}
Email: {lead.email or 'N/A'}
Phone: {lead.phone or 'N/A'}
Company: {lead.company or 'N/A'}
Status: {lead.status}"""


def run_sync():
    """Run full sync"""
    engine = RobustSyncEngine()
    engine.full_sync()


if __name__ == "__main__":
    run_sync()
