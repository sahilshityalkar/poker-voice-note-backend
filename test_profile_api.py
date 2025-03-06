import requests
import json
from datetime import datetime

# Base URL for the API
BASE_URL = "http://127.0.0.1:8000"

# User ID from the provided data
USER_ID = "45c933b1-e868-4033-b6bb-fc85063dbb27"

def test_read_profile():
    """Test GET /profile/profile/ endpoint to read the user profile"""
    url = f"{BASE_URL}/profile/profile/"
    params = {"user_id": USER_ID}
    
    print("\n========= TESTING GET PROFILE =========")
    response = requests.get(url, params=params)
    
    print(f"Status Code: {response.status_code}")
    print(f"Request URL: {response.request.url}")
    if response.status_code == 200:
        data = response.json()
        print(json.dumps(data, indent=2))
        return data
    else:
        print(f"Error: {response.text}")
        return None

def test_update_username():
    """Test PUT /profile/profile/ endpoint to update the user profile"""
    url = f"{BASE_URL}/profile/profile/"
    params = {"user_id": USER_ID}
    
    # Test updating username
    data = {
        "username": "sahil_updated"
    }
    
    print("\n========= TESTING UPDATE USERNAME =========")
    response = requests.put(url, json=data, params=params)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        updated_data = response.json()
        print(json.dumps(updated_data, indent=2))
        
        # Verify username was updated
        print(f"Username updated: {'sahil_updated' == updated_data.get('username')}")
        return updated_data
    else:
        print(f"Error: {response.text}")
        return None

def test_update_languages():
    """Test PUT /profile/profile/languages/ endpoint to update language settings"""
    url = f"{BASE_URL}/profile/profile/languages/"
    params = {"user_id": USER_ID}
    
    # Test updating language settings
    data = {
        "app_language": "en-US",
        "notes_language": "en-GB"
    }
    
    print("\n========= TESTING UPDATE LANGUAGES =========")
    response = requests.put(url, json=data, params=params)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        updated_data = response.json()
        print(json.dumps(updated_data, indent=2))
        
        # Verify languages were updated
        print(f"App language updated: {'en-US' == updated_data.get('app_language')}")
        print(f"Notes language updated: {'en-GB' == updated_data.get('notes_language')}")
        return updated_data
    else:
        print(f"Error: {response.text}")
        return None

def test_reset_profile():
    """Reset profile back to original values for subsequent tests"""
    url = f"{BASE_URL}/profile/profile/"
    params = {"user_id": USER_ID}
    
    # Reset to original values
    data = {
        "username": "sahil",
        "app_language": "en",
        "notes_language": "en"
    }
    
    print("\n========= RESETTING PROFILE =========")
    response = requests.put(url, json=data, params=params)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        reset_data = response.json()
        print(f"Username reset: {'sahil' == reset_data.get('username')}")
        print(f"App language reset: {'en' == reset_data.get('app_language')}")
        print(f"Notes language reset: {'en' == reset_data.get('notes_language')}")
        return reset_data
    else:
        print(f"Error: {response.text}")
        return None

def test_change_phone_number():
    """Test POST /profile/profile/change-phone-number/ endpoint"""
    url = f"{BASE_URL}/profile/profile/change-phone-number/"
    params = {"user_id": USER_ID}
    
    # Note: The profile_api.py has a STATIC_OTP set to "123123"
    data = {
        "new_mobileNumber": "9876543210",
        "otp": "123123"  # Using static OTP as seen in the code
    }
    
    print("\n========= TESTING CHANGE PHONE NUMBER =========")
    response = requests.post(url, json=data, params=params)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        updated_data = response.json()
        print(json.dumps(updated_data, indent=2))
        
        # Verify phone number was updated
        print(f"Phone number updated: {'9876543210' == updated_data.get('mobileNumber')}")
        return updated_data
    else:
        print(f"Error: {response.text}")
        return None

def test_reset_phone_number():
    """Reset phone number back to original for subsequent tests"""
    url = f"{BASE_URL}/profile/profile/change-phone-number/"
    params = {"user_id": USER_ID}
    
    # Reset to original phone number
    data = {
        "new_mobileNumber": "9594870455",
        "otp": "123123"  # Using static OTP as seen in the code
    }
    
    print("\n========= RESETTING PHONE NUMBER =========")
    response = requests.post(url, json=data, params=params)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        reset_data = response.json()
        print(f"Phone number reset: {'9594870455' == reset_data.get('mobileNumber')}")
        return reset_data
    else:
        print(f"Error: {response.text}")
        return None

def run_all_tests():
    """Run all tests in sequence"""
    # First read the profile
    profile = test_read_profile()
    
    if profile:
        # Then test updating the profile
        updated = test_update_username()
        
        # Test updating languages
        if updated:
            languages_updated = test_update_languages()
        
        # Reset the profile back to original values
        if updated:
            reset = test_reset_profile()
        
        # Test changing phone number
        phone_changed = test_change_phone_number()
        
        # Reset phone number back to original
        if phone_changed:
            test_reset_phone_number()
    
    print("\n========= ALL TESTS COMPLETED =========")

if __name__ == "__main__":
    run_all_tests() 