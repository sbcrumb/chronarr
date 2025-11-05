# Maintainarr Webhook Integration

This document describes how to configure Chronarr to receive webhooks from Maintainarr for automatic database cleanup when media is removed.

## Overview

When Maintainarr removes media from your Plex/Radarr/Sonarr collections, Chronarr can automatically remove the corresponding entries from its database to keep it clean and up-to-date.

## Webhook Configuration

### 1. Chronarr Endpoint

The webhook endpoint is available at:
```
http://YOUR_CHRONARR_HOST:8080/webhook/maintainarr
```

**Important**: Use the core Chronarr container port (typically 8080), not the web interface port (8081).

### 2. Maintainarr Configuration

In Maintainarr, create a new webhook notification agent with these settings:

#### Basic Settings
- **Name**: `Chronarr Cleanup`
- **Enabled**: ✅ Checked
- **Agent**: `Webhook`

#### Webhook Configuration
- **Webhook URL**: `http://YOUR_CHRONARR_HOST:8080/webhook/maintainarr`
- **JSON Payload**: Use the template below
- **Auth Header**: *(Leave empty - no authentication required)*

#### JSON Payload Template
Copy and paste this JSON template into the "Json Payload" field:

```json
{
  "notification_type": "{{notification_type}}",
  "subject": "{{subject}}",
  "message": "{{message}}",
  "extra": "{{extra}}"
}
```

**Important Note**: Maintainarr's template variables may not include IMDb IDs directly. The webhook will attempt to extract IMDb IDs from the notification content, but this may require manual configuration or rule setup in Maintainarr to include IMDb IDs in the notification text.

**Alternative Approach**: If Maintainarr doesn't provide IMDb IDs in notifications, you may need to use Chronarr's manual cleanup tools or configure Maintainarr rules to include IMDb information in the message content.

#### Event Types
Select these notification types:
- ✅ **Media Removed From Collection** - Removes media from Chronarr database
- ✅ **Media About To Be Handled** - Optional: Log when media is about to be processed

Optional event types (will be logged but not processed):
- ☐ Media Added To Collection
- ☐ Media Handled
- ☐ Rule Handling Failed
- ☐ Collection Handling Failed

## Supported Operations

### Movies
When a movie is removed from Maintainarr:
- Chronarr checks if the movie exists in its database (by IMDb ID)
- If found, removes the movie record from the `movies` table
- Logs the deletion operation

### TV Series
When a TV series is removed from Maintainarr:
- Chronarr checks if the series exists in its database (by IMDb ID)
- If found, removes all episode records from the `episodes` table
- Removes the series record from the `series` table
- Logs the deletion operation with episode count

## Webhook Payload

Maintainarr sends webhook payloads using template variables that you configure:

```json
{
  "notification_type": "Media Removed",
  "subject": "Example Movie (2023)",
  "message": "Removed movie Example Movie from collection Action Movies - IMDb: tt1234567",
  "extra": "tt1234567"
}
```

### How It Works
1. **Maintainarr** populates the template variables ({{notification_type}}, {{subject}}, {{message}}, {{extra}})
2. **Chronarr** receives the webhook and parses the content to extract:
   - **IMDb ID**: Extracted from `message`, `subject`, or `extra` fields using pattern matching
   - **Media Type**: Determined from message content keywords or database lookup
   - **Title**: Extracted from `subject` or `message` fields

### Media Identification
Chronarr looks for IMDb IDs in this format:
- `tt1234567` (preferred)
- `1234567` (will be converted to tt1234567)

The webhook handler uses intelligent parsing to:
- Extract IMDb IDs from any field using regex patterns
- Determine if media is a Movie or Series based on keywords or database lookup
- Extract the media title from subject or message content

## Response Format

Chronarr responds with JSON indicating the result:

### Success Response
```json
{
  "status": "success",
  "message": "Processed Media Removed for Example Movie",
  "media_type": "Movie",
  "imdb_id": "tt1234567",
  "removed_count": 1,
  "removed_items": ["Movie: Example Movie (tt1234567)"]
}
```

### Ignored Response
```json
{
  "status": "ignored",
  "reason": "Media tt1234567 not found in database"
}
```

### Error Response
```json
{
  "status": "error",
  "message": "No IMDb ID found in webhook payload"
}
```

## Logging

All webhook activities are logged with details:

```
INFO: Received Maintainarr webhook: Media Removed
INFO: Processing movie deletion for Example Movie (tt1234567)
SUCCESS: Removed movie Example Movie (tt1234567) from database
INFO: Maintainarr cleanup: Media Removed - Movie 'Example Movie' (tt1234567). Removed from database: Movie: Example Movie (tt1234567)
```

## Troubleshooting

### Common Issues

1. **No IMDb ID Found**: 
   - Maintainarr template variables may not include IMDb IDs
   - Check if the notification message contains IMDb information
   - You may need to manually include IMDb IDs in Maintainarr rule configurations

2. **Media Not Found**: 
   - Check if the media exists in Chronarr's database
   - Verify the IMDb ID matches between Maintainarr and Chronarr

3. **Connection Issues**:
   - Ensure Chronarr core container is accessible on port 8080
   - Check firewall settings and network connectivity

4. **Authentication Errors**:
   - No authentication is required for the webhook endpoint
   - Ensure you're using the core container port, not web interface port

5. **Test Notifications**:
   - Test notifications (like the one you just sent) will be acknowledged but not processed
   - Real media removal events will trigger the cleanup process

### Testing the Webhook

You can test the webhook manually using curl:

```bash
curl -X POST http://YOUR_CHRONARR_HOST:8080/webhook/maintainarr \
  -H "Content-Type: application/json" \
  -d '{
    "notification_type": "Media Removed",
    "subject": "Test Movie (2023)",
    "message": "Removed movie Test Movie from collection - IMDb: tt1234567",
    "extra": "tt1234567"
  }'
```

## Security Considerations

- The webhook endpoint does not require authentication
- Consider using firewalls or network restrictions to limit access
- The endpoint only processes deletion requests, not additions
- All operations are logged for audit purposes

## Integration Benefits

- **Automatic Cleanup**: Keeps Chronarr database synchronized with your media collection
- **Accurate Statistics**: Dashboard stats reflect only currently available media
- **Reduced Manual Maintenance**: No need to manually clean up orphaned entries
- **Audit Trail**: All deletions are logged with full details

## Version Compatibility

- Chronarr: v2.8.0+
- Maintainarr: All versions with webhook support
- Requires Chronarr core container (processing container), not web-only container