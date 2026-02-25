import json
import os

def main():
    try:
        with open("token.json", "r") as f:
            token_data = json.load(f)
            
        secret_data = {
            "GOOGLE_TOKEN_JSON": json.dumps(token_data),
            "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", "your_groq_api_key_here")
        }
        
        with open("modal_secret.json", "w") as f:
            json.dump(secret_data, f, indent=2)
            
        print("Successfully created modal_secret.json")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
