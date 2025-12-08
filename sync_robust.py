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
            "Contacted": Config.TRELLO_CONTACTED_LIST_ID,
            "Qualified": Config.TRELLO_QUALIFIED_LIST_ID,
            "Closed": Config.TRELLO_CLOSED_LIST_ID,
        }
        # Default to New list if status not recognized
        return mapping.get(normalized_status, Config.TRELLO_NEW_LIST_ID)

    def _map_list_id_to_status(self, list_id: str) -> str:
        """Map Trello list ID to Google Sheets status"""
        reverse_mapping = {
            Config.TRELLO_NEW_LIST_ID: "New",
            Config.TRELLO_CONTACTED_LIST_ID: "Contacted",
            Config.TRELLO_QUALIFIED_LIST_ID: "Qualified",
            Config.TRELLO_CLOSED_LIST_ID: "Closed",
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
        
        New Process (Idempotent & Duplicate-Safe):
        1. Upsert record to DB (creates PENDING if new)
        2. Check if card exists in DB (card_id != PENDING_*)
        3. If card exists: Verify list position, move if needed
        4. If no card: Search Trello by lead_id in description
        5. If found in Trello: Link to DB, verify/move to correct list
        6. If not found: Create new card in status-appropriate list
        7. Store card_id in DB
        
        Returns:
            Result dict with actions taken
        """
        print("\n" + "=" * 70)
        print("SYNC FROM GOOGLE SHEETS")
        print("=" * 70)
        
        try:
            # Extract lead data
            lead_id = lead_data.get("lead_id", "")
            lead_name = lead_data.get("lead_name", "")
            lead_email = lead_data.get("lead_email", "")
            lead_phone = lead_data.get("lead_phone", "")
            lead_company = lead_data.get("lead_company", "")
            sheet_status = lead_data.get("status", "New")

            # ===================================================================
            # VALIDATION: Check if all required fields are present
            # ===================================================================
            # Validate required fields - both name AND email must be present
            if not lead_name or not lead_email:
                print(f"⚠️  Incomplete data - skipping card creation")
                print(f"   Name: {lead_name or 'MISSING'}")
                print(f"   Email: {lead_email or 'MISSING'}")
                print(f"   Waiting for complete data before creating Trello card...")
                return {
                    "success": False, 
                    "error": "Incomplete data",
                    "reason": "Both name and email are required to create a card",
                    "skipped": True
                }

            # Generate lead_id from Name+Email if not provided
            if not lead_id:
                lead_id = str(f"{lead_name}_{lead_email}")[:20]
                print(f"Generated lead_id from Name+Email: {lead_id}")

            print(f"✓ All required fields present")
            print(f"Lead ID: {lead_id}")
            print(f"Name: {lead_name}")
            print(f"Email: {lead_email}")
            print(f"Phone: {lead_phone or 'N/A'}")
            print(f"Company: {lead_company or 'N/A'}")
            print(f"Status: {sheet_status}")

            # ===================================================================
            # STEP 1: Upsert record in database (always succeeds)
            # ===================================================================
            db_updated, action, db_record = self.db.upsert_record_from_sheets(
                lead_id, lead_name, lead_email, lead_phone, lead_company, sheet_status
            )
            
            if not db_updated:
                print(f"✗ Failed to upsert database record")
                self.stats["errors"] += 1
                return {"success": False, "error": "Database upsert failed"}

            print(f"✓ Database {action}: {lead_id}")

            # ===================================================================
            # STEP 2: Check if card is already linked in database
            # ===================================================================
            card_id = db_record.get("card_id")
            card_is_linked = card_id and not card_id.startswith("PENDING_")

            if card_is_linked:
                # Card exists and is linked
                print(f"  Card already linked: {card_id}")
                
                # Update card details in Trello (name, email, phone, company may have changed)
                print(f"  Updating card information...")
                card_title = f"{lead_name} ({lead_email})" if lead_email else lead_name
                card_description = self._format_card_description_for_new_card(
                    lead_id, lead_name, lead_email, lead_phone, lead_company, sheet_status
                )
                
                # Verify card is in correct list based on status
                expected_list_id = self._map_status_to_list_id(sheet_status)
                current_list_id = db_record.get("trello_list_id")
                
                # Update card (title, description, and list if needed)
                update_success = self.task_client.update_task(
                    card_id,
                    status=sheet_status if current_list_id != expected_list_id else None,
                    title=card_title,
                    notes=card_description
                )
                
                if update_success:
                    print(f"  ✓ Card information updated")
                    if current_list_id != expected_list_id:
                        # Update DB with new list ID
                        self.db.update_from_trello_move(card_id, expected_list_id, sheet_status)
                        print(f"  ✓ Card moved to {sheet_status} list")
                        self.stats["statuses_updated"] += 1
                    else:
                        print(f"  ✓ Card already in correct list ({sheet_status})")
                else:
                    print(f"  ✗ Failed to update card")
                    self.stats["errors"] += 1
                
                return {"success": True, "action": "updated", "lead_id": lead_id, "card_id": card_id}

            # ===================================================================
            # STEP 3: Card not linked - Search Trello for existing card
            # ===================================================================
            print(f"  Card not linked - searching Trello...")
            
            try:
                all_cards = self.task_client.get_all_tasks()
                print(f"  Found {len(all_cards)} cards in Trello board")
            except Exception as e:
                print(f"  ✗ Error fetching Trello cards: {str(e)}")
                all_cards = []
            
            # Search for card by lead_id in description
            existing_card = None
            for card in all_cards:
                card_desc = card.notes or ""
                # Look for "Lead ID: {lead_id}" in description
                if f"Lead ID: {lead_id}" in card_desc:
                    existing_card = card
                    print(f"  ✓ Found existing card by lead_id: {card.id}")
                    break
            
            # ===================================================================
            # STEP 4a: Card found in Trello - Link it to database
            # ===================================================================
            if existing_card:
                print(f"  Linking existing Trello card to database...")
                
                # Update DB with actual card info
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
                print(f"  ✓ Card linked: {existing_card.id}")
                
                # Verify card is in correct list
                expected_list_id = self._map_status_to_list_id(sheet_status)
                if existing_card.list_id != expected_list_id:
                    print(f"  Card in wrong list - moving to {sheet_status}...")
                    card_title = f"{lead_name} ({lead_email})" if lead_email else lead_name
                    success = self.task_client.update_task(
                        existing_card.id,
                        status=sheet_status,
                        title=card_title
                    )
                    if success:
                        self.db.update_from_trello_move(existing_card.id, expected_list_id, sheet_status)
                        print(f"  ✓ Card moved to correct list")
                        self.stats["statuses_updated"] += 1
                else:
                    print(f"  ✓ Card already in correct list")
                
                return {"success": True, "action": "linked", "lead_id": lead_id, "card_id": existing_card.id}

            # ===================================================================
            # STEP 4b: Card not found - Create new card in Trello
            # ===================================================================
            print(f"  No existing card found - creating new card...")
            
            # Determine target list from status (defaults to New)
            target_list_id = self._map_status_to_list_id(sheet_status)
            
            if not target_list_id:
                print(f"  ✗ Cannot map status '{sheet_status}' to list ID")
                self.stats["errors"] += 1
                return {"success": False, "error": f"Cannot map status {sheet_status} to Trello list"}
            
            # Format card title and description
            card_title = f"{lead_name} ({lead_email})" if lead_email else lead_name
            card_description = self._format_card_description_for_new_card(
                lead_id, lead_name, lead_email, lead_phone, lead_company, sheet_status
            )
            
            # Create card in Trello
            try:
                new_card_id = self.task_client.create_task_in_list(
                    target_list_id,
                    card_title,
                    card_description
                )
            except Exception as e:
                print(f"  ✗ Failed to create card: {str(e)}")
                new_card_id = None
            
            if new_card_id:
                print(f"  ✓ Card created in {sheet_status} list: {new_card_id}")
                
                # Update database with real card ID
                self.db.create_record_with_card(
                    lead_id=lead_id,
                    lead_name=lead_name,
                    lead_email=lead_email,
                    lead_phone=lead_phone,
                    lead_company=lead_company,
                    card_id=new_card_id,
                    card_title=card_title,
                    trello_list_id=target_list_id,
                    current_status=sheet_status
                )
                self.stats["cards_created"] += 1
                
                print(f"  ✓ Database updated with card_id")
                print("-" * 70)
                print("✓ Google Sheets sync complete\n")
                return {"success": True, "action": "created", "lead_id": lead_id, "card_id": new_card_id}
            else:
                print(f"  ✗ Card creation failed")
                self.stats["errors"] += 1
                print("-" * 70)
                print("✗ Sync failed\n")
                return {"success": False, "error": "Failed to create Trello card"}

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
                    lead_name = db_record.get("lead_name")
                    lead_email = db_record.get("lead_email")
                    
                    sheet_updated = self.lead_client.update_lead_status(
                        lead_id, 
                        new_status,
                        lead_name=lead_name,
                        lead_email=lead_email
                    )
                    
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


