# Poker Voice Notes Backend

Backend for a Poker Voice Notes application with audio processing and player analysis.

## New Feature: Player Analysis API

The application now includes a Player Analysis API that can analyze a player's strengths and weaknesses based on their recorded notes.

### Player Analysis Endpoints

1. **Analyze a Player**
   - `POST /player-analysis/players/{player_id}/analyze`
   - Requires a user_id header
   - Analyzes all notes for a specified player and generates strengths and weaknesses

2. **Get Latest Player Analysis**
   - `GET /player-analysis/players/{player_id}/latest-analysis`
   - Retrieves the most recent analysis for a player

3. **Get Player Analysis History**
   - `GET /player-analysis/players/{player_id}/analysis-history`
   - Retrieves the complete history of analyses for a player
   - Supports pagination with `limit` and `skip` query parameters

### Example Usage

```bash
# Analyze a player
curl -X 'POST' \
  'http://127.0.0.1:8000/player-analysis/players/{player_id}/analyze' \
  -H 'accept: application/json' \
  -H 'user-id: {your-user-id}'

# Get latest analysis
curl -X 'GET' \
  'http://127.0.0.1:8000/player-analysis/players/{player_id}/latest-analysis' \
  -H 'accept: application/json' \
  -H 'user-id: {your-user-id}'

# Get analysis history
curl -X 'GET' \
  'http://127.0.0.1:8000/player-analysis/players/{player_id}/analysis-history?limit=5&skip=0' \
  -H 'accept: application/json' \
  -H 'user-id: {your-user-id}'
```

## API Documentation

When the application is running, you can access the full API documentation at:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc` 