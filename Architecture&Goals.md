Two-Way Sync System (Trello ↔ Google Sheets)
Automated Lead & Task Synchronization with FastAPI, SQLite, and Webhooks
Overview

This project implements a two-way synchronization system between:

Trello — used as the task tracker

Google Sheets — used as the lead tracker (chosen instead of Airtable due to webhook limitations)

FastAPI backend — sync logic, storage, and webhook receiver

SQLite + SQLAlchemy — mapping and deduplication

The system listens to platform events using webhooks and keeps Google Sheets and Trello in sync without duplicates.

The project was:

Planned using ChatGPT

Implemented using GitHub Copilot + Claude Haiku 4.4

Webhooks successfully configured

Google Sheets sync logic completed

Trello → Sheets sync logic pending at submission deadline (to be completed later)

This project was developed from scratch as a learning exercise and demonstrates a working foundation for cross-platform synchronization.

Why Google Sheets Instead of Airtable

Originally Airtable was considered. However:

Airtable’s webhook automation requires a paid plan

Google Sheets offers free automation using Apps Script

Google Sheets API supports CRUD operations needed for sync

Therefore, Google Sheets replaced Airtable in the final implementation.

Project Goals

Maintain a unified system that syncs tasks and leads across platforms

Automatically reflect updates in both directions (Trello ↔ Google Sheets)

Use webhooks instead of periodic polling

Ensure sync is idempotent: no duplicate tasks, safe repeated runs

Maintain a mapping table for cross-platform linking

Use a clean, modular backend architecture (FastAPI, SQLAlchemy, SQLite)

High-Level Architecture
           Trello (Board, Lists, Cards, Webhooks)
                     │
                     ▼  Webhook Event (JSON)
                FastAPI Backend
                     │
                     ▼
          SQLite Mapping Database
                     │
                     ▼
              Google Sheets (Sheets API / Apps Script)

Database Design (SQLite)

Table: mapping

Field	Type	Description
id	Integer (primary key)	Internal mapping ID
trello_card_id	Text	ID of Trello card
sheet_row_id	Text	Row index or unique ID in Google Sheet
last_synced	DateTime	Timestamp of the last sync — used for deduplication and logging
Sync Flow
Trello → FastAPI → Google Sheets

Trello webhook triggers on events such as card creation, updates, or list changes

FastAPI receives the webhook, processes the payload

The mapping table is checked/updated as required

The corresponding row in Google Sheets is created or updated

Google Sheets → FastAPI → Trello

A Google Apps Script trigger (e.g., onEdit) detects changes in Google Sheets

Script sends the change payload to FastAPI endpoint

FastAPI updates or creates the corresponding Trello card (name, description, list)

Mapping logic ensures no duplicates

Features Implemented

FastAPI backend

SQLite database with mapping model (SQLAlchemy)

Google Sheets integration via Sheets API + Apps Script webhook emitter

Trello webhook receiver endpoint

Webhook signature verification (if needed)

Idempotent sync logic with mapping table

Error handling and logging for sync operations

Modular architecture and clean code structure

Pending / Post-Deadline Work

Complete Trello → Google Sheets sync logic

Implement conflict resolution for bi-directional updates

Add retry queue for failed sync operations

Optional background worker for batched syncs

Optionally build a UI dashboard to display sync logs and status

Technology Stack
Component	Technology
Backend framework	FastAPI
ORM	SQLAlchemy
Database	SQLite
Task Tracker	Trello API + Webhooks
Lead Tracker	Google Sheets API + Apps Script
Authentication & Config	Environment variables / API tokens
Logging	Standard Python logging
Planning	ChatGPT
Coding assistance	GitHub Copilot + Claude Haiku 4.4
Getting Started — Setup Instructions
1. Install dependencies
pip install -r requirements.txt

2. Set environment variables

Example:

GOOGLE_SHEETS_ID=...
GOOGLE_SERVICE_ACCOUNT=...
TRELLO_KEY=...
TRELLO_TOKEN=...
WEBHOOK_SECRET=...

3. Start the FastAPI server
uvicorn main:app --reload

4. Expose server publicly for webhooks (for development)

Use ngrok, or deploy to a platform that exposes HTTPS endpoints

5. Register webhooks

In Trello: create a webhook pointing to your FastAPI endpoint

In Google Sheets: use Apps Script to trigger webhook on edits

Learning and Takeaways

Designed a cross-platform sync architecture from scratch

Implemented mapping and deduplication logic with SQLite

Integrated multiple third-party APIs (Trello + Google Sheets)

Built webhook-based automation with clean sync flows

Managed backward compatibility: switched from Airtable to Google Sheets due to webhook access

Handled real-world concerns: error handling, idempotency, modular code structure

Conclusion

This project demonstrates a working foundation for asynchronous, bi-directional synchronization between task and lead tracking platforms.

Although the initial deadline required only part of the functionality, the core architecture is stable, modular, and designed to be extended. I plan to complete the remaining sync logic as a personal project to reinforce the learning.

If desired, I can also generate:

A visual architecture diagram (PNG or ASCII) to embed in README

A shorter “summary README” version for GitHub front page

A testing plan and instructions for how to verify sync manually

Let me know if you want me to produce any of those.

