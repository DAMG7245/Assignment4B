from fastapi import FastAPI
import uvicorn
from routes.rag_api_routes import router
  # Use underscores instead of hyphens

app = FastAPI(title="RAG API Service")  # Updated title to match your project name

# Register routes
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)