import urllib.parse
import urllib.request
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import boto3
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SSM_PARAMETER_NAME

CLIENT_ID = GOOGLE_CLIENT_ID
CLIENT_SECRET = GOOGLE_CLIENT_SECRET
REDIRECT_URI = "http://127.0.0.1:8082/callback"

# Google Health API granular scopes — writeonly is required to log workouts.
# Include readonly too so the same token can also fetch existing data if needed.
SCOPES = " ".join([
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.writeonly",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
])

if not CLIENT_ID or not CLIENT_SECRET:
    print("Error: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
    exit(1)

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/callback':
            query = urllib.parse.parse_qs(parsed_path.query)
            if 'code' in query:
                auth_code = query['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"Authorization successful! You can close this window and check the console.")
                
                # Exchange code for tokens
                exchange_code_for_tokens(auth_code)
                
                # Stop the server
                raise KeyboardInterrupt()
            else:
                print(f"\nAuthorization failed. Received query parameters: {query}")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authorization failed. Check the console for details.")
        else:
            self.send_response(404)
            self.end_headers()

def get_auth_url():
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent" # Force consent to ensure we get a refresh token
    }
    return f"{base_url}?{urllib.parse.urlencode(params)}"

def exchange_code_for_tokens(code):
    print("\nExchanging authorization code for Google tokens...")
    token_url = "https://oauth2.googleapis.com/token"
    
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }).encode()
    
    req = urllib.request.Request(token_url, data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    
    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode())
            refresh_token = response_data.get("refresh_token")
            
            if refresh_token:
                print(f"Successfully retrieved tokens. Refresh token: {refresh_token[:5]}...")
                store_token_in_ssm(refresh_token)
            else:
                print("Error: No refresh token returned. Did you include 'prompt=consent'?")
            
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.read().decode()}")
    except Exception as e:
        print(f"Error: {e}")

def store_token_in_ssm(refresh_token):
    print(f"Storing Google refresh token in AWS SSM Parameter Store under {SSM_PARAMETER_NAME}...")
    try:
        ssm = boto3.client('ssm')
        ssm.put_parameter(
            Name=SSM_PARAMETER_NAME,
            Description='Google Health API Refresh Token for fitsync',
            Value=refresh_token,
            Type='SecureString',
            Overwrite=True
        )
        print("Successfully stored token in SSM!")
    except Exception as e:
        print(f"Failed to store token in SSM: {e}")
        print("Make sure you have valid AWS credentials configured.")

if __name__ == '__main__':
    print(f"Please configure your Google Cloud OAuth Client with the following Authorized Redirect URI:\n{REDIRECT_URI}\n")
    print("Then, visit this URL in your browser to authorize:")
    print("-" * 80)
    print(get_auth_url())
    print("-" * 80)
    print("\nStarting local server on port 8080 to listen for the callback...")
    
    server_address = ('127.0.0.1', 8082)
    httpd = HTTPServer(server_address, OAuthCallbackHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
