from google import genai

client = genai.Client(api_key="AQ.Ab8RN6Klmfv-7CUrJwjq0Ybf5XPVVyyES1vvVxMYJTgr5mYeGg")

models = client.models.list()

for m in models:
    print(m.name)