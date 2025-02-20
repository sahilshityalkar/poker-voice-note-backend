# test_poker_api.py
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_root_endpoint():
    """Test the root endpoint returns correct status"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Poker Analysis API is running"}

def test_analyze_game_endpoint():
    """Test the analyze-game endpoint with sample poker game data"""
    test_notes = [
        "I had King Queen suited in early position.",
        "I raised to 3 big blinds.",
        "Player 2 called from middle position.",
        "Player 3 folded.",
        "The flop came King Hearts, Seven Clubs, Two Diamonds.",
        "I bet half pot.",
        "Player 2 called.",
        "Turn was Ace of Spades.",
        "I checked, Player 2 bet pot, I called.",
        "River was Three of Hearts.",
        "I checked, Player 2 went all-in.",
        "I folded thinking they had an Ace.",
        "Player 2 showed Ace King offsuit and won the pot."
    ]
    
    response = client.post(
        "/analyze-game",
        json={"notes": test_notes}
    )
    
    assert response.status_code == 200
    assert "success" in response.json()
    assert "analysis" in response.json()
    assert response.json()["success"] == True
    assert isinstance(response.json()["analysis"], str)
    assert len(response.json()["analysis"]) > 0

def test_analyze_game_empty_notes():
    """Test the analyze-game endpoint with empty notes"""
    response = client.post(
        "/analyze-game",
        json={"notes": []}
    )
    assert response.status_code == 200

def test_analyze_game_invalid_input():
    """Test the analyze-game endpoint with invalid input"""
    response = client.post(
        "/analyze-game",
        json={"invalid_field": []}
    )
    assert response.status_code == 422

def test_analyze_game_non_string_notes():
    """Test the analyze-game endpoint with non-string notes"""
    response = client.post(
        "/analyze-game",
        json={"notes": [1, 2, 3]}
    )
    assert response.status_code == 422

if __name__ == "__main__":
    pytest.main([__file__])