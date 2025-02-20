# test.py
import requests

def analyze_game(notes):
    response = requests.post("http://localhost:8000/analyze-game", json={"notes": notes})
    if response.status_code == 200:
        print("Success!")
        print("\nAnalysis:\n", response.json()["analysis"])
        print("-" * 20)
    else:
        print("Error:", response.status_code)
        print(response.json())

def test_poker_analysis():
    # Test Case 1: Standard Hand
    notes1 = [
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
    print("Test Case 1: Standard Hand")
    analyze_game(notes1)

    # Test Case 2: Bluff Attempt
    notes2 = [
        "I had 7 2 offsuit in late position.",
        "I raised to 3 big blinds.",
        "Only the big blind called.",
        "Flop was 3 4 5 all diamonds.",
        "Big blind checked.",
        "I bet half pot as a bluff.",
        "Big blind called.",
        "Turn was a King of Spades.",
        "Big blind checked.",
        "I bet pot.",
        "Big blind folded."
    ]
    print("Test Case 2: Bluff Attempt")
    analyze_game(notes2)

    # Test Case 3: Passive Play
    notes3 = [
        "I had pocket Aces.",
        "I limped in early position.",
        "Several players limped behind.",
        "Flop was 2 7 8 rainbow.",
        "I checked.",
        "Another player bet.",
        "I called.",
        "Turn was a Queen.",
        "I checked.",
        "The other player bet.",
        "I called.",
        "River was a King.",
        "I checked.",
        "The other player bet.",
        "I called.",
        "He had 7 8 for two pair."
    ]
    print("Test Case 3: Passive Play")
    analyze_game(notes3)

    # Test Case 4: Overbet Shove
    notes4 = [
        "I had Ace King suited on the button",
        "Villain raised preflop to 3bb from UTG",
        "I called",
        "Flop came Ace 10 2 rainbow",
        "Villain bet 4bb",
        "I called",
        "Turn was a Queen of Spades",
        "Villain checked",
        "I bet 10bb",
        "Villain called",
        "River was a Jack of hearts completing the straight",
        "Villain checked",
        "I jammed all in for 5x the pot",
        "Villain called and had King Queen"
    ]
    print("Test Case 4: Overbet Shove")
    analyze_game(notes4)
if __name__ == "__main__":
    test_poker_analysis()