import os
import sys
from openai import AzureOpenAI

# Force terminal input and output encoding to UTF-8 to prevent ASCII codec errors on macOS/Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stdin.reconfigure(encoding='utf-8')

# 1. Basic connection configurations.
# The API key is read from the environment so it is never committed to source control.
# Set it before running, e.g.:  export AZURE_OPENAI_KEY="<your-key>"
endpoint = "https://aoai-ucla-prjs.openai.azure.com/"
deployment = "gpt-5.4"
subscription_key = os.environ.get("AZURE_OPENAI_KEY", "")
if not subscription_key:
    raise RuntimeError("AZURE_OPENAI_KEY environment variable is not set.")
api_version = "2024-12-01-preview"

# Initialize the Azure OpenAI client
client = AzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)

# 2. Establish "Memory": Use a list to store the entire conversation history
# The system prompt sets the core behavior and persona of this AI
chat_history = [
    {"role": "system", "content": "You are a helpful AI assistant."}
]

print("🤖 Chat system initialized! (Type 'quit' or 'exit' to end the conversation)")
print("-" * 50)

# 3. Enter the continuous conversation loop
while True:
    # Receive user input
    user_input = input("\nYou: ")
    
    # Set exit conditions
    if user_input.lower() in ['quit', 'exit']:
        print("Ending conversation. See you next time!")
        break
        
    # [Crucial Step A] Append the user's latest message to the conversation history
    chat_history.append({"role": "user", "content": user_input})
    
    try:
        # Call the API and pass the *entire* chat history so it remembers the context
        response = client.chat.completions.create(
            model=deployment,
            messages=chat_history,
            temperature=0.7
        )
        
        # Extract the AI's response content
        ai_reply = response.choices[0].message.content
        
        print(f"\nAI: {ai_reply}")
        print("-" * 50)
        
        # [Crucial Step B] Append the AI's response to the conversation history!
        # This is strictly required so the model remembers its own replies in the next turn.
        chat_history.append({"role": "assistant", "content": ai_reply})
        
    except Exception as e:
        print(f"\n[System Error]: {e}")
        # If a network error or timeout occurs, remove the last user message to prevent memory corruption
        chat_history.pop()