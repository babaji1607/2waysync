from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from sync_robust import RobustSyncEngine
from utils.logger import setup_logger
from utils.database import init_db

logger = setup_logger(__name__)

# Global instances
robust_sync_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):    # lifespan of the application
    """Lifespan context manager for startup and shutdown"""
    global robust_sync_engine

    logger.info("Starting application initialization")

    try:
        # Initialize database
        init_db()
        logger.info("Database initialized")
        
        robust_sync_engine = RobustSyncEngine()
        logger.info("Application initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize application: {str(e)}")

    yield

    logger.info("Shutting down application")


# Create FastAPI app
app = FastAPI(
    title="Lead-Task Sync API",
    description="Webhook-based sync: Google Sheets ↔ Database ↔ Trello",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.head("/")
async def root_head() -> dict:
    """HEAD endpoint for Trello webhook verification"""
    return {}


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "message": "Application is running"
    }


@app.get("/debug/sheet-structure")
async def debug_sheet_structure() -> dict:
    """Debug endpoint to inspect Google Sheet structure and records"""
    try:
        from lead_client import LeadClient
        
        client = LeadClient()
        
        # Get headers
        headers = client.worksheet.row_values(1)
        
        # Get first 5 records
        records = client.worksheet.get_all_records()[:5]
        
        return {
            "status": "success",
            "headers": headers,
            "first_5_records": records,
            "total_records": len(client.worksheet.get_all_records()),
            "message": "Sheet structure retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Debug endpoint error: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }


@app.get("/debug/database-records")
async def debug_database_records() -> dict:
    """Debug endpoint to inspect database records"""
    try:
        from utils.database import SyncDatabase
        
        db = SyncDatabase()
        records = db.get_all_mappings()
        
        return {
            "status": "success",
            "total_records": len(records),
            "records": records,
            "message": "Database records retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Debug endpoint error: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }

@app.post("/webhook/sheets")
async def webhook_sheets(payload: dict) -> dict:
    """
    Google Sheets webhook - Syncs immediately to Trello and Database
    """
    try:
        print("\n" + "="*70)
        print("GOOGLE SHEETS WEBHOOK")
        print("="*70)
        print(payload)
        print("="*70 + "\n")
        
        fields = payload.get("fields") or payload.get("data", {})   # Support both "fields" and "data" keys

        if not fields:
            logger.warning("No fields in webhook payload")
            raise HTTPException(status_code=400, detail="No data in webhook payload")

        # Extract lead fields from Google Sheets data (handle both lowercase and uppercase keys)
        lead_id = fields.get("id") or fields.get("Id") or ""
        lead_name = fields.get("name") or fields.get("Name") or ""
        lead_email = fields.get("email") or fields.get("Email") or ""
        lead_phone = fields.get("phone") or fields.get("Phone") or ""
        lead_status = fields.get("status") or fields.get("Status") or "New"
        lead_company = fields.get("company") or fields.get("Company") or ""
        lead_notes = fields.get("notes") or fields.get("Notes") or ""

        # Prepare lead data
        lead_data = {
            "lead_id": lead_id,
            "lead_name": lead_name,
            "lead_email": lead_email,
            "lead_phone": lead_phone,
            "lead_company": lead_company,
            "status": lead_status,
            "notes": lead_notes
        }
        print(lead_data)

        # Sync immediately: Sheets → DB → Trello
        result = robust_sync_engine.sync_from_sheets_webhook(lead_data)
        # sync logic 

        return {
            "status": "processed",
            "message": f"Synced: {lead_name}",
            "sync_result": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sheet webhook processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")




@app.post("/webhook/trello")
async def webhook_trello(request: Request) -> dict:
    """
    Trello webhook - Updates database when card is moved
    Handles: Card moves between lists (status updates)
    Ignores: Card creation events (to prevent circular webhooks)
    """
    try:
        payload = await request.json()
        
        # Extract action details
        action = payload.get("action", {})
        action_type = action.get("type")
        
        # Ignore card creation events (prevents circular webhook loop)
        if action_type == "createCard":
            logger.info("Ignoring createCard event (created by our system)")
            return {"status": "ignored", "reason": "Card creation events not tracked"}
        
        # Only process card move/update actions
        if action_type != "updateCard":
            return {"status": "ignored", "reason": f"Action type '{action_type}' not tracked"}

        # Extract card and list information from action data
        action_data = action.get("data", {})
        card = action_data.get("card", {})
        card_id = card.get("id")
        list_after = action_data.get("listAfter")
        
        # Only process if card was moved to a different list
        if not list_after:
            return {"status": "ignored", "reason": "Not a list move action"}
            
        new_list_id = list_after.get("id")
        new_status_name = list_after.get("name")
        
        # Validate required fields
        if not card_id or not new_list_id or not new_status_name:
            logger.warning(f"Missing required fields in Trello webhook payload")
            return {"status": "error", "reason": "Missing required fields"}

        # Map list name to status
        status_mapping = {
            "New": "New",
            "Contacted": "Contacted",
            "Qualified": "Qualified",
            "Closed": "Closed"
        }
        new_status = status_mapping.get(new_status_name, new_status_name)

        # Update database
        from utils.database import SyncDatabase
        from lead_client import LeadClient
        
        db = SyncDatabase()
        success, updated_record = db.update_from_trello_move(
            card_id=card_id,
            new_list_id=new_list_id,
            new_status=new_status
        )

        if success:
            logger.info(f"✓ Trello card moved: {card_id} → {new_status}")
            
            # Update Google Sheets with new status
            lead_id = updated_record.get("lead_id")
            lead_name = updated_record.get("lead_name")
            lead_email = updated_record.get("lead_email")
            
            if lead_id:
                try:
                    lead_client = LeadClient()
                    sheets_updated = lead_client.update_lead_status(
                        lead_id, 
                        new_status,
                        lead_name=lead_name,
                        lead_email=lead_email
                    )
                    if sheets_updated:
                        logger.info(f"✓ Google Sheets updated: {lead_id} → {new_status}")
                    else:
                        logger.warning(f"Failed to update Google Sheets for lead: {lead_id}")
                except Exception as e:
                    logger.error(f"Error updating Google Sheets: {str(e)}")
            
            return {
                "status": "success",
                "action": action_type,
                "card_id": card_id,
                "new_status": new_status,
                "record": updated_record,
                "sheets_updated": sheets_updated if lead_id else False
            }
        else:
            logger.warning(f"Card {card_id} not found in database")
            return {
                "status": "warning",
                "action": action_type,
                "card_id": card_id,
                "reason": "Card not found in database"
            }

    except Exception as e:
        logger.error(
            f"Trello webhook processing failed: {str(e)}",
            extra={"extra_data": {"error": str(e)}}
        )
        raise HTTPException(status_code=500, detail=f"Trello webhook failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
