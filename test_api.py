import requests

def test_players_with_analysis():
    url = "http://127.0.0.1:8000/players-api/players-with-analysis"
    headers = {
        "accept": "application/json",
        "user-id": "45c933b1-e868-4033-b6bb-fc85063dbb27"  # Replace with your actual user ID
    }
    
    response = requests.get(url, headers=headers)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        players = response.json()
        print(f"Found {len(players)} players")
        for player in players:
            print(f"Player: {player.get('name')}")
            print(f"Notes Count: {player.get('notes_count')}")
            print(f"Notes Array Length: {len(player.get('notes', []))}")
            print("---")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    test_players_with_analysis() 