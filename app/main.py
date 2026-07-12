from fastapi import FastAPI

app = FastAPI(title="DealPilot")


@app.get("/")
def home():
    return {
        "app": "DealPilot",
        "version": "0.1.0",
        "message": "Welcome to DealPilot!"
    }