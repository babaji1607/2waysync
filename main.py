from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from sync_robust import RobustSyncEngine
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Global instances
robust_sync_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown"""
    global robust_sync_engine

    logger.info("Starting application initialization")

    try:
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
        
        fields = payload.get("fields") or payload.get("data", {})

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

        # Sync immediately: Sheets → DB → Trello
        result = robust_sync_engine.sync_from_sheets_webhook(lead_data)

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
    Trello webhook - Syncs immediately to Google Sheets and Database
    """
    try:
        payload = await request.json()
        
        print("\n" + "="*70)
        print("TRELLO WEBHOOK")
        print("="*70)
        print(payload)
        print("="*70 + "\n")
        
        action = payload.get("action", {})
        action_type = action.get("type")
        if action_type not in ["updateCard", "moveCard", "createCard"]:
            return {"status": "ignored", "action": action_type}

        card_data = action.get("data", {})
        card = card_data.get("card", {})
        card_id = card.get("id")
        card_name = card.get("name", "Unknown")
        list_id = card.get("idList")
        card_desc = card.get("desc", "")

        # Extract lead info from card description
        lead_id = lead_email = lead_phone = lead_company = lead_status = None
        
        if card_desc:
            for line in card_desc.split("\n"):
                if "Lead ID:" in line:
                    lead_id = line.split(":", 1)[1].strip()
                elif "Email:" in line:
                    lead_email = line.split(":", 1)[1].strip()
                elif "Phone:" in line:
                    lead_phone = line.split(":", 1)[1].strip()
                elif "Company:" in line:
                    lead_company = line.split(":", 1)[1].strip()
                elif "Status:" in line:
                    lead_status = line.split(":", 1)[1].strip()

        # Prepare card data
        card_data_dict = {
            "card_id": card_id,
            "card_name": card_name,
            "list_id": list_id,
            "action_type": action_type,
            "lead_id": lead_id,
            "lead_email": lead_email,
            "lead_phone": lead_phone,
            "lead_company": lead_company,
            "lead_status": lead_status
        }

        # Sync immediately: Trello → DB → Sheets
        result = robust_sync_engine.sync_from_trello_webhook(card_data_dict)

        return {
            "status": "processed",
            "message": f"Synced: {card_name}",
            "card_id": card_id,
            "sync_result": result
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
