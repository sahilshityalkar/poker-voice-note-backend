import requests
import json
import random
import time

# Base URL for the API
BASE_URL = "http://127.0.0.1:8000"

def generate_random_phone():
    """Generate a random 10-digit phone number"""
    return f"9{random.randint(100000000, 999999999)}"

def test_new_user_registration():
    """Test the complete flow for registering a new user"""
    # Use a random phone number to avoid conflicts
    phone_number = generate_random_phone()
    username = f"testuser_{random.randint(1000, 9999)}"
    
    print("\n========= TEST: NEW USER REGISTRATION =========")
    print(f"Using phone number: {phone_number}")
    print(f"Using username: {username}")
    
    # Step 1: Initiate authentication (this sends OTP)
    print("\nStep 1: Initiating authentication...")
    auth_url = f"{BASE_URL}/auth/auth"
    auth_data = {"phone_number": phone_number}
    
    auth_response = requests.post(auth_url, json=auth_data)
    print(f"Status Code: {auth_response.status_code}")
    
    if auth_response.status_code != 200:
        print(f"Failed to initiate authentication: {auth_response.text}")
        return None
    
    auth_result = auth_response.json()
    print(f"Auth Response: {json.dumps(auth_result, indent=2)}")
    
    # Verify we got 'user_not_found' since this is a new phone number
    if auth_result.get("status") != "user_not_found":
        print("Warning: Expected 'user_not_found' status but got something else.")
    
    # Step 2: Verify OTP
    print("\nStep 2: Verifying OTP...")
    verify_url = f"{BASE_URL}/auth/verifyotp"
    verify_data = {
        "phone_number": phone_number,
        "otp": "123123"  # Static OTP from the code
    }
    
    verify_response = requests.post(verify_url, json=verify_data)
    print(f"Status Code: {verify_response.status_code}")
    
    if verify_response.status_code != 200:
        print(f"Failed to verify OTP: {verify_response.text}")
        return None
    
    verify_result = verify_response.json()
    print(f"Verify Response: {json.dumps(verify_result, indent=2)}")
    
    # Extract user_id and access_token
    user_id = verify_result.get("user_id")
    access_token = verify_result.get("access_token")
    
    if not user_id or not access_token:
        print("Error: Missing user_id or access_token in response")
        return None
    
    # Verify registration_complete is False (new user)
    if verify_result.get("registration_complete", True):
        print("Error: Expected registration_complete to be False")
        return None
    
    # Step 3: Complete registration
    print("\nStep 3: Completing registration...")
    complete_url = f"{BASE_URL}/auth/complete-registration/{user_id}"
    complete_data = {
        "username": username,
        "app_language": "en",
        "notes_language": "en"
    }
    
    complete_response = requests.post(complete_url, json=complete_data)
    print(f"Status Code: {complete_response.status_code}")
    
    if complete_response.status_code != 200:
        print(f"Failed to complete registration: {complete_response.text}")
        return None
    
    complete_result = complete_response.json()
    print(f"Complete Registration Response: {json.dumps(complete_result, indent=2)}")
    
    # Verify registration is now complete
    if not complete_result.get("registration_complete", False):
        print("Error: Expected registration_complete to be True")
        return None
    
    # Step 4: Verify profile is created
    print("\nStep 4: Verifying profile was created...")
    profile_url = f"{BASE_URL}/profile/profile/"
    profile_params = {"user_id": user_id}
    
    profile_response = requests.get(profile_url, params=profile_params)
    print(f"Status Code: {profile_response.status_code}")
    
    if profile_response.status_code != 200:
        print(f"Failed to retrieve profile: {profile_response.text}")
        return None
    
    profile_result = profile_response.json()
    print(f"Profile Response: {json.dumps(profile_result, indent=2)}")
    
    # Verify profile data matches registration data
    assert profile_result.get("username") == username
    assert profile_result.get("mobileNumber") == phone_number
    assert profile_result.get("user_id") == user_id
    assert profile_result.get("app_language") == "en"
    assert profile_result.get("notes_language") == "en"
    assert profile_result.get("registration_complete") == True
    
    print("\n✅ New user registration test PASSED!")
    return {
        "phone_number": phone_number,
        "username": username,
        "user_id": user_id
    }

def test_existing_user_login(phone_number):
    """Test login flow for an existing user"""
    print("\n========= TEST: EXISTING USER LOGIN =========")
    print(f"Using phone number: {phone_number}")
    
    # Step 1: Initiate authentication
    print("\nStep 1: Initiating authentication...")
    auth_url = f"{BASE_URL}/auth/auth"
    auth_data = {"phone_number": phone_number}
    
    auth_response = requests.post(auth_url, json=auth_data)
    print(f"Status Code: {auth_response.status_code}")
    
    if auth_response.status_code != 200:
        print(f"Failed to initiate authentication: {auth_response.text}")
        return False
    
    auth_result = auth_response.json()
    print(f"Auth Response: {json.dumps(auth_result, indent=2)}")
    
    # Verify we got 'success' since this is an existing phone number
    if auth_result.get("status") != "success":
        print(f"Error: Expected 'success' status but got {auth_result.get('status')}")
        return False
    
    # Step 2: Verify OTP
    print("\nStep 2: Verifying OTP...")
    verify_url = f"{BASE_URL}/auth/verifyotp"
    verify_data = {
        "phone_number": phone_number,
        "otp": "123123"  # Static OTP from the code
    }
    
    verify_response = requests.post(verify_url, json=verify_data)
    print(f"Status Code: {verify_response.status_code}")
    
    if verify_response.status_code != 200:
        print(f"Failed to verify OTP: {verify_response.text}")
        return False
    
    verify_result = verify_response.json()
    print(f"Verify Response: {json.dumps(verify_result, indent=2)}")
    
    # Verify registration_complete is True (existing user)
    if not verify_result.get("registration_complete", False):
        print("Error: Expected registration_complete to be True for existing user")
        return False
    
    # Verify we got a token and user_id
    user_id = verify_result.get("user_id")
    access_token = verify_result.get("access_token")
    
    if not user_id or not access_token:
        print("Error: Missing user_id or access_token in response")
        return False
    
    print("\n✅ Existing user login test PASSED!")
    return True

def test_existing_user_specific(phone_number="9594870455"):
    """Test login with a specific known existing user"""
    print("\n========= TEST: SPECIFIC EXISTING USER LOGIN =========")
    print(f"Using specific phone number: {phone_number}")
    
    # Step 1: Initiate authentication
    print("\nStep 1: Initiating authentication...")
    auth_url = f"{BASE_URL}/auth/auth"
    auth_data = {"phone_number": phone_number}
    
    auth_response = requests.post(auth_url, json=auth_data)
    print(f"Status Code: {auth_response.status_code}")
    
    if auth_response.status_code != 200:
        print(f"Failed to initiate authentication: {auth_response.text}")
        return False
    
    auth_result = auth_response.json()
    print(f"Auth Response: {json.dumps(auth_result, indent=2)}")
    
    # Step 2: Verify OTP
    print("\nStep 2: Verifying OTP...")
    verify_url = f"{BASE_URL}/auth/verifyotp"
    verify_data = {
        "phone_number": phone_number,
        "otp": "123123"  # Static OTP from the code
    }
    
    verify_response = requests.post(verify_url, json=verify_data)
    print(f"Status Code: {verify_response.status_code}")
    
    if verify_response.status_code != 200:
        print(f"Failed to verify OTP: {verify_response.text}")
        return False
    
    verify_result = verify_response.json()
    print(f"Verify Response: {json.dumps(verify_result, indent=2)}")
    
    print("\n✅ Specific existing user login test PASSED!")
    return True

def test_partially_registered_user():
    """Test flow for a user who started registration but didn't complete it"""
    # First create a partial user
    phone_number = generate_random_phone()
    
    print("\n========= TEST: PARTIALLY REGISTERED USER =========")
    print(f"Using phone number: {phone_number}")
    
    # Step 1: Initiate authentication (send OTP for a new user)
    print("\nStep 1: Initiating authentication...")
    auth_url = f"{BASE_URL}/auth/auth"
    auth_data = {"phone_number": phone_number}
    
    auth_response = requests.post(auth_url, json=auth_data)
    print(f"Status Code: {auth_response.status_code}")
    
    if auth_response.status_code != 200:
        print(f"Failed to initiate authentication: {auth_response.text}")
        return False
    
    auth_result = auth_response.json()
    print(f"Auth Response: {json.dumps(auth_result, indent=2)}")
    
    # Step 2: Verify OTP - this creates a user with registration_complete=False
    print("\nStep 2: Verifying OTP...")
    verify_url = f"{BASE_URL}/auth/verifyotp"
    verify_data = {
        "phone_number": phone_number,
        "otp": "123123"  # Static OTP
    }
    
    verify_response = requests.post(verify_url, json=verify_data)
    print(f"Status Code: {verify_response.status_code}")
    
    if verify_response.status_code != 200:
        print(f"Failed to verify OTP: {verify_response.text}")
        return False
    
    verify_result = verify_response.json()
    print(f"Verify Response: {json.dumps(verify_result, indent=2)}")
    
    user_id = verify_result.get("user_id")
    
    # Now simulate the user closing the app without completing registration
    # and coming back later
    
    # Step 3: Login again with the same phone
    print("\nStep 3: Logging in again with same phone number...")
    auth_response2 = requests.post(auth_url, json=auth_data)
    print(f"Status Code: {auth_response2.status_code}")
    
    if auth_response2.status_code != 200:
        print(f"Failed to initiate second authentication: {auth_response2.text}")
        return False
    
    auth_result2 = auth_response2.json()
    print(f"Auth Response: {json.dumps(auth_result2, indent=2)}")
    
    # Step 4: Verify OTP again - this should detect partially registered user
    print("\nStep 4: Verifying OTP again...")
    verify_response2 = requests.post(verify_url, json=verify_data)
    print(f"Status Code: {verify_response2.status_code}")
    
    if verify_response2.status_code != 200:
        print(f"Failed to verify OTP: {verify_response2.text}")
        return False
    
    verify_result2 = verify_response2.json()
    print(f"Verify Response: {json.dumps(verify_result2, indent=2)}")
    
    # Verify registration_complete is still False and user_id is the same
    if verify_result2.get("registration_complete", True):
        print("Error: Expected registration_complete to be False")
        return False
    
    if verify_result2.get("user_id") != user_id:
        print(f"Error: Expected same user_id but got different ones. Original: {user_id}, New: {verify_result2.get('user_id')}")
        return False
    
    # Step 5: Now complete registration
    print("\nStep 5: Completing registration...")
    username = f"testuser_{random.randint(1000, 9999)}"
    complete_url = f"{BASE_URL}/auth/complete-registration/{user_id}"
    complete_data = {
        "username": username,
        "app_language": "en",
        "notes_language": "en"
    }
    
    complete_response = requests.post(complete_url, json=complete_data)
    print(f"Status Code: {complete_response.status_code}")
    
    if complete_response.status_code != 200:
        print(f"Failed to complete registration: {complete_response.text}")
        return False
    
    complete_result = complete_response.json()
    print(f"Complete Registration Response: {json.dumps(complete_result, indent=2)}")
    
    # Verify registration is now complete
    if not complete_result.get("registration_complete", False):
        print("Error: Expected registration_complete to be True")
        return False
    
    print("\n✅ Partially registered user test PASSED!")
    return True

def run_all_tests():
    """Run all the authentication flow tests"""
    print("\n========= RUNNING AUTH FLOW TESTS =========")
    
    # First test partially registered user flow
    partially_registered_result = test_partially_registered_user()
    
    # First test logging in with a known existing user
    existing_result = test_existing_user_specific()
    
    # Then test registering a new user
    user_data = test_new_user_registration()
    
    if user_data:
        # If new user was created successfully, test logging in with that user
        time.sleep(1)  # Small delay to make sure data is consistent
        login_result = test_existing_user_login(user_data["phone_number"])
    
    print("\n========= ALL TESTS COMPLETED =========")

if __name__ == "__main__":
    run_all_tests() 