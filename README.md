# Lead-Task Sync - Two-Way Webhook Sync

A real-time bidirectional sync system that keeps Google Sheets and Trello in perfect sync using webhooks and a SQLite database as the central authority.

## What It Does

- **Google Sheets ↔ Trello Sync**: When you add/update a lead in Sheets, a Trello card is created/updated automatically
- **Trello ↔ Google Sheets Sync**: When you move a card in Trello, the status is updated back in Sheets automatically
- **Database Authority**: SQLite database tracks all lead-card relationships and prevents conflicts
- **Real-Time**: Changes sync immediately via webhooks (no polling, no delays)
- **Loop Prevention**: Smart echo detection prevents infinite update loops

## Architecture

### System Components

```
┌─────────────────────┐
│   Google Sheets     │
│  (Lead Tracker)     │
└──────────┬──────────┘
           │ Webhook
           ↓
    ┌──────────────┐
    │  FastAPI     │
    │  Server      │
    └──────┬───────┘
           │
      ┌────┴────┐
      ↓         ↓
┌─────────┐ ┌──────────────┐
│ Trello  │ │  SQLite DB   │
│ Board   │ │ (Authority)  │
└─────────┘ └──────────────┘
      ↑
      │ Webhook
      └──────────────
```

### How It Works

**Three Layers:**

1. **Data Sources**: Google Sheets and Trello Board
2. **API Server**: FastAPI with two webhook endpoints
3. **Database**: SQLite with lead-to-card mapping

**Key Table Structure:**
```
lead_card_mapping:
- lead_id (Google Sheets identifier)
- lead_name, lead_email, lead_phone, lead_company
- card_id (Trello card identifier)
- card_title, trello_list_id
- current_status
- last_sync_source (sheets/trello - for echo prevention)
```

### Sync Flow

#### Google Sheets → Trello
```
1. User adds/updates lead in Sheets
2. Google Apps Script sends webhook
3. API extracts: Name, Email, Phone, Company, Status
4. Generate lead_id from Name+Email
5. Create/Update record in Database
6. Check: Does Trello card exist?
   - YES: Verify it's in correct list, move if needed
   - NO: Create new card in Trello
7. Update Database with card_id
8. Done! (Instant)
```

#### Trello → Google Sheets
```
1. User moves card in Trello board
2. Trello sends webhook
3. API extracts: card_id, new_list_id, lead_id (from description)
4. Find record in Database by card_id
5. Check: Is this an echo from Sheets? (last_sync_source == sheets)
   - YES: Skip (prevent infinite loop)
   - NO: Continue
6. Determine new status from list_id
7. Update Database with new status
8. Update Google Sheets status
9. Done! (Instant)
```

## Setup & Installation

### Prerequisites
- Python 3.8+
- Google Sheets with Google Apps Script
- Trello board with API key and token
- Ngrok or public URL for webhook endpoints

### Step 1: Clone & Install Dependencies

```bash
cd 2waysync
pip install -r requirements.txt
```

### Step 2: Create Configuration Files

Create `.env` in the project root:

```env
# Google Sheets Configuration
GOOGLE_SHEETS_ID=your_sheet_id_here
GOOGLE_CREDENTIALS_FILE=sustained-edge-473607-h2-1b45f6cf1e18.json

# Trello Configuration
TRELLO_API_KEY=your_api_key_here
TRELLO_API_TOKEN=your_api_token_here
TRELLO_BOARD_ID=your_board_id_here

# Trello List IDs (Status -> List Mapping)
TRELLO_NEW_LIST_ID=list_id_for_new_leads
TRELLO_IN_PROGRESS_LIST_ID=list_id_for_contacted
TRELLO_QUALIFIED_LIST_ID=list_id_for_qualified
TRELLO_DONE_LIST_ID=list_id_for_closed

# Server Configuration
HOST=0.0.0.0
PORT=8000
APP_ENV=development
LOG_LEVEL=INFO
```

### Step 3: Set Up Google Apps Script

In your Google Sheet, add this Apps Script (Tools → Script editor):

```javascript
function onEdit(e) {
  var sheet = e.source.getActiveSheet();
  var range = e.range;
  
  // Only process "Leads" sheet
  if (sheet.getName() !== "Leads") return;
  
  var row = range.getRow();
  var col = range.getColumn();
  
  // Skip header row
  if (row === 1) return;
  
  // Get the entire row
  var values = sheet.getRange(row, 1, 1, sheet.getLastColumn()).getValues()[0];
  
  // Map columns: Name, Email, Phone, Company, Status, Notes
  var payload = {
    action: "updated",
    timestamp: new Date().toISOString(),
    sheet_name: sheet.getName(),
    row_id: row.toString(),
    fields: {
      Name: values[0] || "",
      Email: values[1] || "",
      Phone: values[2] || "",
      Company: values[3] || "",
      Status: values[4] || "New",
      Notes: values[5] || ""
    }
  };
  
  // Send to your webhook
  var options = {
    method: "post",
    payload: JSON.stringify(payload),
    contentType: "application/json"
  };
  
  UrlFetchApp.fetch("https://your-webhook-url/webhook/sheets", options);
}
```

### Step 4: Set Up Trello Webhook

Create a Trello webhook using Trello API:

```bash
curl -X POST https://api.trello.com/1/webhooks \
  -d "callbackURL=https://your-webhook-url/webhook/trello" \
  -d "idModel=YOUR_BOARD_ID" \
  -d "key=YOUR_API_KEY" \
  -d "token=YOUR_API_TOKEN"
```

### Step 5: Run the Server

```bash
fastapi dev main.py
```

Server will start at `http://localhost:8000`

Check health:
```bash
curl http://localhost:8000/health
```

## API Endpoints

### Health Check
```
GET /health
```
Returns: `{"status": "healthy", "message": "Application is running"}`

### Google Sheets Webhook
```
POST /webhook/sheets
```
Called automatically by Google Apps Script when sheet is edited.

### Trello Webhook
```
POST /webhook/trello
```
Called automatically by Trello when card is moved/updated.

## Database Files

- `sync_mapping.db` - SQLite database (auto-created on first run)
- `logs/` - Application logs

## File Structure

```
2waysync/
├── main.py                 # FastAPI app & webhook endpoints
├── sync_robust.py          # Sync logic & database authority
├── lead_client.py          # Google Sheets API client
├── task_client.py          # Trello API client
├── utils/
│   ├── database.py         # SQLite database management
│   ├── config.py           # Configuration loading
│   ├── logger.py           # Logging setup
│   └── models.py           # Data models
├── .env                    # Configuration (create this)
├── requirements.txt        # Python dependencies
├── sync_mapping.db         # SQLite database (auto-created)
└── logs/                   # Application logs (auto-created)
```

## Environment Variables

### Google Sheets
- `GOOGLE_SHEETS_ID` - Your Google Sheet ID
- `GOOGLE_CREDENTIALS_FILE` - Path to service account JSON file

### Trello
- `TRELLO_API_KEY` - Trello API key
- `TRELLO_API_TOKEN` - Trello API token
- `TRELLO_BOARD_ID` - Target Trello board ID

### Trello Lists (Status Mapping)
- `TRELLO_NEW_LIST_ID` - List for "New" status
- `TRELLO_IN_PROGRESS_LIST_ID` - List for "Contacted" status
- `TRELLO_QUALIFIED_LIST_ID` - List for "Qualified" status
- `TRELLO_DONE_LIST_ID` - List for "Closed" status

### Server
- `HOST` - Server host (default: 0.0.0.0)
- `PORT` - Server port (default: 8000)
- `APP_ENV` - Environment (development/production)
- `LOG_LEVEL` - Logging level (INFO/DEBUG/ERROR)

## How to Get Credentials

### Google Sheets
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project
3. Enable Google Sheets API
4. Create a Service Account
5. Download JSON credentials
6. Share your Sheet with the service account email

### Trello API Key & Token
1. Go to [Trello API Key](https://trello.com/app-key)
2. Copy your API Key
3. Click "Token" link to generate token
4. Get your Board ID from board URL: `trello.com/b/{BOARD_ID}/...`

### List IDs in Trello
1. Open board in Trello
2. Right-click on any card in a list
3. Open in browser console: Right-click → Inspect → Console
4. Run: `fetch('/1/boards/BOARD_ID/lists', {headers: {Authorization: 'OAuth oauth_consumer_key="KEY", oauth_token="TOKEN"'}}).then(r=>r.json()).then(lists => console.table(lists.map(l => ({name: l.name, id: l.id}))))`
5. Copy the list IDs

## Workflow Example

### Adding a Lead
```
1. Open Google Sheet
2. Add row: "John Doe", "john@example.com", "9876543210", "Acme Inc", "New", "Notes here"
3. Press Enter
4. Webhook triggers immediately
5. ✓ Record created in Database
6. ✓ Trello card created in "New" list
7. Done in ~1-2 seconds!
```

### Updating Lead Status
```
1. Open Google Sheet
2. Change status from "New" to "Contacted"
3. Press Enter
4. Webhook triggers immediately
5. ✓ Database updated with new status
6. ✓ Trello card moved to "Contacted" list
7. Done in ~1-2 seconds!
```

### Moving Card in Trello
```
1. Open Trello board
2. Drag card from "New" to "Qualified" list
3. Webhook triggers immediately
4. ✓ Database updated with new list
5. ✓ Google Sheet status changed to "Qualified"
6. Done in ~1-2 seconds!
```

## Troubleshooting

### Cards not creating in Trello
- Check Trello API credentials in `.env`
- Verify TRELLO_BOARD_ID is correct
- Check server logs: `tail -f logs/app.log`

### Status not updating in Sheets
- Verify Google Sheets credentials
- Check that sheet columns are: Name, Email, Phone, Company, Status, Notes
- Review logs for errors

### Webhooks not firing
- Verify webhook URLs are public (use Ngrok if running locally)
- Check webhook registration in Google Apps Script and Trello
- Look for webhook delivery failures in Trello admin

### Infinite loops / Echo syncing
- Check `last_sync_source` in database to verify echo prevention
- Review logs for "Skipping - this change originated from Sheets" messages

## Performance Notes

- First webhook response: ~1-2 seconds
- Database operations: <100ms
- API calls to Google/Trello: 500-2000ms depending on network

## Security

- Use environment variables for all credentials (never commit `.env`)
- Service account should have minimal permissions
- Trello token should be kept private
- Use HTTPS for webhook endpoints in production

## License

MIT

## Support

For issues:
1. Check logs: `tail logs/app.log`
2. Verify credentials in `.env`
3. Test webhooks are configured correctly
4. Check database exists: `ls -la sync_mapping.db`

