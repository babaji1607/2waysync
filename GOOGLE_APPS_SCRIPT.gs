/**
 * Lead Tracker → FastAPI Webhook Script
 * Auto-syncs Google Sheets edits to FastAPI server via webhook
 * 
 * SETUP INSTRUCTIONS:
 * ==================
 * 1. Open your Google Sheet: https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit
 * 2. Go to Extensions → Apps Script
 * 3. Delete any existing code
 * 4. Paste THIS ENTIRE SCRIPT
 * 5. Save (Ctrl+S)
 * 6. Run initializeSheet() once (select function and press ▶️ play button)
 * 7. Setup trigger for onEdit:
 *    - Click ⏰ (Triggers icon on left sidebar)
 *    - Click "Add Trigger" button
 *    - Choose:
 *      • Function: onEdit
 *      • Event source: From spreadsheet
 *      • Event type: On edit
 *      • Notifications: Don't notify
 *    - Click "Save & Authorize"
 * 8. Done! Your sheet now syncs to FastAPI
 */

// ============================================================================
// CONFIGURATION - UPDATE THESE VALUES
// ============================================================================

const WEBHOOK_URL = "https://donald-frontierless-stifledly.ngrok-free.dev/webhook/sheets";
const SHEET_NAME = "Leads";
const HEADER_ROW = 1;

// Column configuration - MUST match your Google Sheet headers
const COLUMNS = {
  NAME: "Name",
  EMAIL: "Email",
  PHONE: "Phone",
  COMPANY: "Company",
  STATUS: "Status",
  NOTES: "Notes"
};

const STATUS_OPTIONS = ["NEW", "CONTACTED", "QUALIFIED", "CLOSED"];

// ============================================================================
// MAIN TRIGGER - Auto-runs when sheet is edited
// ============================================================================

/**
 * Runs automatically when ANY cell is edited in the sheet
 * Captures the edited row and sends to FastAPI webhook
 */
function onEdit(e) {
  try {
    if (!e || !e.range) {
      logEvent("❌ No event data");
      return;
    }

    const sheet = e.range.getSheet();
    const row = e.range.getRow();
    const col = e.range.getColumn();
    const editedValue = e.value;

    // Only process edits on the monitored sheet
    if (sheet.getName() !== SHEET_NAME) {
      logEvent(`⏭️ Edit on different sheet (${sheet.getName()}) - skipping`);
      return;
    }

    // Skip header row
    if (row === HEADER_ROW) {
      logEvent("⏭️ Header row edited - skipping");
      return;
    }

    logEvent(`📝 Edit detected: Row ${row}, Column ${col}`);
    logEvent(`   Edited value: ${editedValue}`);

    // Get the full row data
    const rowData = getRowData(sheet, row);

    if (!rowData || Object.keys(rowData).length === 0) {
      logEvent(`⚠️  Row ${row} is empty - skipping`);
      return;
    }

    // Prepare webhook payload
    const payload = {
      action: "updated",
      timestamp: new Date().toISOString(),
      sheet_name: SHEET_NAME,
      row_id: String(row),
      fields: rowData,
      data: rowData
    };

    logEvent(`📦 Sending webhook for: ${rowData.Name} (Status: ${rowData.Status})`);
    logEvent(`   Email: ${rowData.Email}`);
    logEvent(`   URL: ${WEBHOOK_URL}`);

    sendWebhook(payload);

  } catch (error) {
    logEvent(`❌ Error in onEdit: ${error.message}`);
  }
}

// ============================================================================
// WEBHOOK SENDER
// ============================================================================

/**
 * Sends the webhook to FastAPI server
 */
function sendWebhook(payload) {
  try {
    const options = {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
      headers: {
        "User-Agent": "Google-Sheets-Script",
        "X-Webhook-Source": "google-sheets"
      },
      timeout: 30
    };

    const response = UrlFetchApp.fetch(WEBHOOK_URL, options);
    const code = response.getResponseCode();
    const text = response.getContentText();

    if (code >= 200 && code < 300) {
      logEvent(`✅ Webhook sent! Status: ${code}`);
      logEvent(`   Response: ${text}`);
    } else {
      logEvent(`⚠️  Webhook error ${code}`);
      logEvent(`   Response: ${text}`);
    }

  } catch (error) {
    logEvent(`❌ Webhook failed: ${error.message}`);
  }
}

// ============================================================================
// DATA EXTRACTION
// ============================================================================

/**
 * Reads a full row and returns as object with column headers as keys
 */
function getRowData(sheet, row) {
  try {
    const headers = getHeaders(sheet);
    const lastColumn = Math.max(...Object.keys(headers).map(key => headers[key]));

    if (row > sheet.getLastRow()) {
      return null;
    }

    const range = sheet.getRange(row, 1, 1, lastColumn);
    const values = range.getValues()[0];

    const rowData = {};
    for (const [key, colIndex] of Object.entries(headers)) {
      const cellValue = values[colIndex - 1] !== undefined ? String(values[colIndex - 1] || "").trim() : "";
      rowData[key] = cellValue;
    }

    logEvent(`✓ Read row ${row}: ${JSON.stringify(rowData)}`);
    return rowData;

  } catch (error) {
    logEvent(`❌ Error reading row: ${error.message}`);
    return null;
  }
}

/**
 * Get header columns with their indices
 */
function getHeaders(sheet) {
  try {
    const headerRow = sheet.getRange(HEADER_ROW, 1, 1, sheet.getLastColumn());
    const headerValues = headerRow.getValues()[0];

    const headers = {};
    let colIndex = 1;

    for (const colName of Object.values(COLUMNS)) {
      const foundIndex = headerValues.findIndex(h => String(h).trim() === colName);
      if (foundIndex !== -1) {
        headers[colName] = foundIndex + 1;
        colIndex = foundIndex + 2;
      }
    }

    return headers;
  } catch (error) {
    logEvent(`❌ Error reading headers: ${error.message}`);
    return {};
  }
}

// ============================================================================
// SETUP & INITIALIZATION
// ============================================================================

/**
 * Initialize sheet with headers and dummy data
 * RUN THIS ONCE to set up your sheet
 */
function initializeSheet() {
  logEvent("🔧 Initializing sheet...");

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);

  // Create sheet if it doesn't exist
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    logEvent(`✓ Created new sheet: ${SHEET_NAME}`);
  }

  // Add headers
  const headerValues = [
    Object.values(COLUMNS)
  ];
  sheet.getRange(1, 1, 1, headerValues[0].length).setValues(headerValues);

  // Format headers
  const headerRange = sheet.getRange(1, 1, 1, headerValues[0].length);
  headerRange.setFontWeight("bold");
  headerRange.setBackground("#1f77b4");
  headerRange.setFontColor("#ffffff");
  headerRange.setHorizontalAlignment("center");

  // Add dummy leads data
  const dummyData = [
    ["John Smith", "john.smith@techcorp.com", "+1-555-0101", "Tech Corp", "NEW", "Initial contact"],
    ["Sarah Johnson", "sarah.j@startup.io", "+1-555-0102", "Startup Inc", "CONTACTED", "Demo scheduled"],
    ["Mike Chen", "mike@enterprise.com", "+1-555-0103", "Enterprise Ltd", "QUALIFIED", "Awaiting signature"],
    ["Emma Wilson", "emma.wilson@agency.net", "+1-555-0104", "Creative Agency", "NEW", "Referred by client"],
    ["David Brown", "david.b@finance.co", "+1-555-0105", "Finance Group", "CONTACTED", "Follow up tomorrow"],
    ["Lisa Anderson", "lisa@healthcare.org", "+1-555-0106", "Healthcare Plus", "QUALIFIED", "Final approval pending"],
    ["Tom Martinez", "tom.m@retail.com", "+1-555-0107", "Retail Solutions", "NEW", "Cold outreach"],
    ["Jessica Lee", "jessica@marketing.pro", "+1-555-0108", "Marketing Pro", "CONTACTED", "Waiting for callback"],
    ["Chris Taylor", "chris.taylor@consulting.biz", "+1-555-0109", "Consulting Group", "CLOSED", "Deal closed - $50k"],
    ["Rachel Green", "rachel@education.edu", "+1-555-0110", "Education Institute", "NEW", "Inbound inquiry"]
  ];

  sheet.getRange(HEADER_ROW + 1, 1, dummyData.length, headerValues[0].length).setValues(dummyData);

  // Auto-resize columns
  for (let i = 1; i <= headerValues[0].length; i++) {
    sheet.autoResizeColumn(i);
  }

  // Add data validation for Status column
  const statusColumn = Object.values(COLUMNS).indexOf(COLUMNS.STATUS) + 1;
  const dataValidation = SpreadsheetApp.newDataValidation()
    .requireValueInList(STATUS_OPTIONS, true)
    .setAllowInvalid(false)
    .setHelpText("Select: NEW, CONTACTED, QUALIFIED, or CLOSED")
    .build();

  sheet.getRange(HEADER_ROW + 1, statusColumn, sheet.getMaxRows() - HEADER_ROW).setDataValidation(dataValidation);

  logEvent(`✅ Sheet initialized successfully!`);
  logEvent(`   Headers: ${headerValues[0].join(", ")}`);
  logEvent(`   Dummy data rows: ${dummyData.length}`);
  logEvent(`   Status column: ${COLUMNS.STATUS} (with dropdown validation)`);
  logEvent(`💡 Now go to Extensions → Apps Script → Triggers to set up the onEdit trigger`);
}

// ============================================================================
// TESTING FUNCTIONS
// ============================================================================

/**
 * Test the webhook by sending a sample payload
 * Run this to verify your webhook URL is correct
 */
function testWebhook() {
  logEvent("🧪 Testing webhook...");

  const testPayload = {
    action: "test",
    timestamp: new Date().toISOString(),
    sheet_name: SHEET_NAME,
    row_id: "2",
    fields: {
      "Name": "Test Lead",
      "Email": "test@example.com",
      "Phone": "+1-555-0000",
      "Company": "Test Company",
      "Status": "NEW",
      "Notes": "This is a test webhook from Google Apps Script"
    }
  };

  logEvent(`📦 Test payload: ${JSON.stringify(testPayload)}`);
  sendWebhook(testPayload);
  logEvent("✓ Test webhook sent!");
}

/**
 * Manually send row data from a specific row number
 */
function testSendRow(rowNumber = 2) {
  logEvent(`🧪 Testing row ${rowNumber}...`);

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) {
    logEvent(`❌ Sheet "${SHEET_NAME}" not found!`);
    return;
  }

  const rowData = getRowData(sheet, rowNumber);
  if (!rowData || Object.keys(rowData).length === 0) {
    logEvent(`❌ Row ${rowNumber} is empty!`);
    return;
  }

  const payload = {
    action: "test",
    timestamp: new Date().toISOString(),
    sheet_name: SHEET_NAME,
    row_id: String(rowNumber),
    fields: rowData
  };

  logEvent(`📦 Sending row ${rowNumber}: ${JSON.stringify(payload)}`);
  sendWebhook(payload);
}

/**
 * Show debugging information about the sheet
 */
function debugSheet() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);

  if (!sheet) {
    logEvent(`❌ Sheet "${SHEET_NAME}" not found!`);
    logEvent(`💡 Available sheets: ${SpreadsheetApp.getActiveSpreadsheet().getSheets().map(s => s.getName()).join(", ")}`);
    return;
  }

  logEvent("\n📋 SHEET DEBUG INFO");
  logEvent(`   Sheet name: ${SHEET_NAME}`);
  logEvent(`   Last row: ${sheet.getLastRow()}`);
  logEvent(`   Last column: ${sheet.getLastColumn()}`);

  const headers = getHeaders(sheet);
  logEvent(`   Headers: ${JSON.stringify(headers)}`);

  logEvent("\n   First 3 data rows:");
  for (let row = HEADER_ROW + 1; row <= Math.min(HEADER_ROW + 3, sheet.getLastRow()); row++) {
    const data = getRowData(sheet, row);
    logEvent(`     Row ${row}: ${JSON.stringify(data)}`);
  }

  logEvent(`\n⚙️  Webhook Configuration:`);
  logEvent(`   URL: ${WEBHOOK_URL}`);
  logEvent(`   Sheet: ${SHEET_NAME}`);
}

// ============================================================================
// UTILITIES
// ============================================================================

/**
 * Logging function - logs to Apps Script console
 */
function logEvent(message) {
  Logger.log(message);
  console.log(message);
}

/**
 * Menu for easy access to functions
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Lead Sync')
    .addItem('Initialize Sheet', 'initializeSheet')
    .addSeparator()
    .addItem('Test Webhook', 'testWebhook')
    .addItem('Test Send Row 2', 'testSendRow')
    .addItem('Debug Info', 'debugSheet')
    .addToUi();
}
