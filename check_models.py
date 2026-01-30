import google.generativeai as genai

# Configure with your key
genai.configure(api_key="AIzaSyAvVPPu7MKe8bQfXvdfxkbje22abmASc_s")

print("--- CHECKING AVAILABLE MODELS ---")
try:
    for m in genai.list_models():
        # Only show models that can generate content (chat/text)
        if 'generateContent' in m.supported_generation_methods:
            print(f"AVAILABLE: {m.name}")
except Exception as e:
    print(f"Error: {e}")