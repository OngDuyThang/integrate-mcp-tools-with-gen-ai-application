import io
import os
from contextlib import asynccontextmanager, redirect_stdout
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field
from strands import Agent
from strands.models.gemini import GeminiModel
from strands.models.mistral import MistralModel
from strands.tools.mcp import MCPClient
from strands.types.exceptions import ModelThrottledException

# --- Config ---
load_dotenv()
buf = io.StringIO()

# --- Constants ---
if "GEMINI_API_KEY" not in os.environ or "MISTRAL_API_KEY" not in os.environ:
    raise ValueError(
        "Please set the GEMINI_API_KEY and MISTRAL_API_KEY environment variable.")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
BASE_DIR = Path(__file__).resolve().parent

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://0.0.0.0:8000/mcp")

# --- MCP Client ---
mcp_client = MCPClient(
    lambda: streamablehttp_client(MCP_SERVER_URL))

# --- Pydantic Models ---


class ChatRequest(BaseModel):
    prompt: str = Field(description="The user's question or instruction")
    model_name: str = Field(
        default="gemini", description="The model to use (gemini or mistral)")


class ChatResponse(BaseModel):
    response: str
    model_used: str = "gemini"

# --- Lifespan Manager ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the lifecycle of the application.
    Opens the MCP connection at startup and closes it at shutdown.
    """
    print("Startup: Connecting to Weather MCP Server...")

    # Context manager to keep the connection open for the app's life
    with mcp_client:
        try:
            # 1. Fetch available tools
            app.state.tools = mcp_client.list_tools_sync()
            print(f"Startup: Discovered tools: {[t for t in app.state.tools]}")

            # 2. Initialize the Models
            # Gemini
            app.state.gemini_model = GeminiModel(
                model_id="gemini-2.5-flash",
                client_args={
                    "api_key": GEMINI_API_KEY,
                },
                params={
                    "temperature": 0.7,
                    "max_output_tokens": 2048,
                    "top_p": 0.9,
                    "top_k": 40
                }
            )

            # Mistral
            app.state.mistral_model = MistralModel(
                model_id="mistral-large-latest",
                api_key=MISTRAL_API_KEY,
                max_tokens=1000,
                temperature=0.7,
                top_p=0.9
            )

            print("Startup: Models initialized successfully.")
            yield

        except Exception as e:
            print(f"Startup Error: {e}")
            raise

    print("Shutdown: Closed MCP connection.")

# --- FastAPI App ---
app = FastAPI(title="Weather Gen AI Agent", lifespan=lifespan)

# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def chat_bot_ui():
    html_path = BASE_DIR / "static" / "index.html"
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/converse", response_model=ChatResponse)
async def converse(request: ChatRequest):
    """
    Send a prompt to the agent and get a response.
    """
    # Select model dynamically
    if request.model_name == "gemini":
        model = app.state.gemini_model
    elif request.model_name == "mistral":
        model = app.state.mistral_model

    # Create the Strands Agent instance with selected model
    agent = Agent(
        model=model,
        tools=app.state.tools,
        system_prompt="You are a helpful assistant. Use the available weather tools to answer questions."
    )

    try:
        # Invoke the agent
        with redirect_stdout(buf):
            response_text = agent(prompt=request.prompt)

        return ChatResponse(response=str(response_text), model_used=request.model_name)

    except ModelThrottledException:
        raise HTTPException(
            status_code=429, detail="Model quota exceeded. Please try again later.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Run Server ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
