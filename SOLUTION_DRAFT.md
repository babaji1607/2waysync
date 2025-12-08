# Solution Draft: Fixed Google Sheets → Trello Sync Logic

## Problem Analysis

### Current Issues:
1. **Flawed list mapping**: .env.example has `TRELLO_IN_PROGRESS_LIST_ID` but code expects `TRELLO_CONTACTED_LIST_ID`
2. **Card creation timing**: When Google Sheets webhook fires, card should be created immediately in correct list based on status
3. **Circular webhook problem**: Creating card in Trello triggers webhook back to our app
4. **Duplicate prevention**: Need to ensure no duplicate cards are created
5. **Idempotency**: Multiple webhook fires should not create multiple cards

## Solution Architecture

### 1. Status → List Mapping (Fixed)

**Update Config to match actual list names:**
- "New" → `TRELLO_NEW_LIST_ID` (69302eea6f04a447f64cb1d1)
- "Contacted" → `TRELLO_CONTACTED_LIST_ID` (6931c3cc4d6af12296f494be)
- "Qualified" → `TRELLO_QUALIFIED_LIST_ID` (69328ef5fc40468a853a096e)
- "Closed" → `TRELLO_CLOSED_LIST_ID` (6931c3f1be3977233a430960)

Default to "New" if status is not one of these.

### 2. Google Sheets Webhook Flow (Redesigned)

```
Google Sheets Webhook Fires
    ↓
1. Extract data: lead_id, name, email, phone, company, status
    ↓
2. Upsert to Database (creates or updates record with PENDING card_id)
    ↓
3. Check if card exists in database (card_id != PENDING_*)
    ↓
   YES: Card exists                    NO: Card doesn't exist
    ↓                                    ↓
4a. Get expected list from status    4b. Search Trello by lead_id in description
    ↓                                    ↓
5a. Compare with current list         Found?  YES ↓         NO ↓
    ↓                                    ↓                   ↓
   Same? → Done                      5b. Link card         5c. Create new card
   Different? → Move card             to DB record          in correct list
    ↓                                    ↓                   ↓
6a. Update DB with new list          6b. Check list       6c. Store card_id
                                      position              in DB record
                                         ↓
                                     Move if wrong
```

### 3. Circular Webhook Prevention

**Strategy: Ignore `createCard` events in Trello webhook**

When our app creates a card, Trello fires a webhook with `action.type = "createCard"`. 

**Solution:**
- Trello webhook only processes `updateCard` events (list moves)
- Trello webhook ignores `createCard` events
- This breaks the circular loop

**Updated Trello Webhook Logic:**
```python
if action_type == "createCard":
    return {"status": "ignored", "reason": "Card creation events not tracked"}

if action_type != "updateCard":
    return {"status": "ignored", "reason": "Only card moves are tracked"}
```

### 4. Duplicate Prevention

**Three-layer protection:**

1. **Database uniqueness**: `card_id` is UNIQUE in database
   - Attempting to create duplicate throws DB constraint error
   - Catch error and link to existing record instead

2. **Pre-creation search**: Before creating card, search Trello for:
   - Cards with `Lead ID: {lead_id}` in description
   - If found, link to existing card instead of creating new one

3. **Idempotency flag**: Add `sync_in_progress` field to prevent race conditions
   - Set flag when processing starts
   - Skip processing if flag is already set
   - Clear flag when done

### 5. Card Format

**Card Title:**
```
{name} ({email})
```
Example: `mohit (mohit@email.com)`

**Card Description:**
```
Lead ID: {lead_id}
Name: {name}
Email: {email}
Phone: {phone or 'N/A'}
Company: {company or 'N/A'}
Status: {status}
Source: Google Sheets
```

### 6. Implementation Steps

#### Step 1: Fix Config
Update `utils/config.py` to use `TRELLO_CONTACTED_LIST_ID` instead of `TRELLO_IN_PROGRESS_LIST_ID`

#### Step 2: Update Status Mapping in sync_robust.py
```python
def _map_status_to_list_id(self, sheet_status: str) -> Optional[str]:
    """Map Google Sheets status to Trello list ID"""
    normalized_status = sheet_status.strip().title() if sheet_status else "New"
    mapping = {
        "New": Config.TRELLO_NEW_LIST_ID,
        "Contacted": Config.TRELLO_CONTACTED_LIST_ID,
        "Qualified": Config.TRELLO_QUALIFIED_LIST_ID,
        "Closed": Config.TRELLO_CLOSED_LIST_ID,
    }
    # Default to New if status not recognized
    return mapping.get(normalized_status, Config.TRELLO_NEW_LIST_ID)
```

#### Step 3: Refactor sync_from_sheets_webhook

**New Logic:**
1. Extract and validate data
2. Upsert to database (always succeeds, creates PENDING record)
3. Check if card_id exists and is not PENDING
   - **YES**: Card linked → verify list, move if needed
   - **NO**: Card not linked → search or create

**Search Logic:**
- Fetch all cards from board
- Search by `Lead ID: {lead_id}` in description
- If found: Link to DB, verify/move to correct list
- If not found: Create new card in correct list

**Create Logic:**
- Determine target list from status (default: New)
- Create card with formatted title and description
- Store card_id in database immediately
- Trello webhook will fire but will be ignored (createCard event)

#### Step 4: Update Trello Webhook
Add protection against createCard events:
```python
if action_type == "createCard":
    return {"status": "ignored", "reason": "Card creation ignored"}
```

Only process `updateCard` with `listAfter` (list changes).

#### Step 5: Add Duplicate Protection in Database

Add method to handle duplicate card_id gracefully:
```python
def link_existing_card(self, lead_id: str, card_id: str, ...):
    """Link existing card to lead, handle duplicates"""
    try:
        # Try to update record
        record = query.filter(lead_id == lead_id).first()
        record.card_id = card_id
        commit()
    except IntegrityError:
        # Card already linked to another lead - this is a problem
        rollback()
        # Log and investigate
```

## Testing Plan

### Test Case 1: New Lead in Sheets (Status: New)
**Expected:**
1. DB record created with PENDING card_id
2. Card created in "New" list
3. DB updated with real card_id
4. Trello webhook fires (createCard) → ignored
**Result:** 1 DB record, 1 Trello card in "New" list

### Test Case 2: New Lead in Sheets (Status: Contacted)
**Expected:**
1. DB record created
2. Card created in "Contacted" list (not "New")
3. DB updated with card_id
**Result:** Card directly in "Contacted" list

### Test Case 3: Update Existing Lead (Status Change)
**Expected:**
1. DB record updated
2. Card found by card_id
3. Card moved to new list
4. Trello webhook fires (updateCard) → processed → DB updated
**Result:** Card in correct new list

### Test Case 4: Duplicate Prevention
**Action:** Fire same webhook twice quickly
**Expected:**
1. First request: Creates record + card
2. Second request: Finds existing record, finds existing card by lead_id search, links
**Result:** Only 1 card created

### Test Case 5: Manual Card Creation in Trello
**Action:** Manually create card with lead_id in description
**Expected:**
1. Next Sheets webhook finds card by lead_id search
2. Links card to DB record
3. No duplicate created
**Result:** Manual card is linked, no duplicate

### Test Case 6: Card Moved in Trello UI
**Expected:**
1. Trello webhook (updateCard) fires
2. DB updated with new list/status
3. Google Sheets NOT updated (out of scope for now)
**Result:** DB reflects new status

## Edge Cases Handled

1. **Invalid status**: Defaults to "New" list
2. **Missing list IDs**: Returns error, doesn't create card
3. **Trello API failure**: Logs error, keeps PENDING in DB
4. **Card deleted in Trello**: Search fails, creates new card
5. **Multiple cards with same lead_id**: Takes first match (by search order)
6. **Network timeout**: Retry logic in task_client handles it
7. **Webhook fires during card creation**: Ignored (createCard type)

## Configuration Updates Needed

### .env / config.env
```env
# Replace TRELLO_IN_PROGRESS_LIST_ID with:
TRELLO_CONTACTED_LIST_ID=6931c3cc4d6af12296f494be
```

### utils/config.py
```python
TRELLO_CONTACTED_LIST_ID = os.getenv("TRELLO_CONTACTED_LIST_ID", "")

_raw_mapping = {
    "New": TRELLO_NEW_LIST_ID,
    "Contacted": TRELLO_CONTACTED_LIST_ID,  # Updated
    "Qualified": TRELLO_QUALIFIED_LIST_ID,
    "Closed": TRELLO_CLOSED_LIST_ID,
}
```

## Summary

### Key Changes:
1. ✅ Fix status → list mapping (Contacted instead of In Progress)
2. ✅ Default unknown statuses to "New"
3. ✅ Create cards immediately on Sheets webhook
4. ✅ Search for existing cards before creating
5. ✅ Ignore createCard webhooks from Trello (prevent circular loop)
6. ✅ Only process updateCard (list moves) from Trello
7. ✅ Maintain idempotency through DB constraints
8. ✅ Prevent duplicates through pre-creation search

### Benefits:
- **Instant sync**: Cards appear in Trello immediately
- **Correct placement**: Cards go to status-appropriate list, not always "New"
- **No duplicates**: Multiple layers of protection
- **No infinite loops**: Ignoring createCard breaks circular webhook chain
- **Resilient**: Handles edge cases gracefully
- **Idempotent**: Safe to retry/replay webhooks

Would you like me to implement this solution?
