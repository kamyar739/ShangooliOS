from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates

from web.db import (
    get_artwork,
    get_collection,
    get_collections,
    update_artwork,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ShangooliOS")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/")
def home(request: Request):
    collections = get_collections()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"collections": collections},
    )

@app.get("/collections/{collection_code}")
def collection_page(request: Request, collection_code: str):
    collection, artworks = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="collection.html",
        context={
            "collection": collection,
            "artworks": artworks,
        },
    )

@app.get("/artworks/{artwork_code}")
def artwork_page(request: Request, artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context={"artwork": artwork},
    )

@app.post("/artworks/{artwork_code}")
def save_artwork(
    request: Request,
    artwork_code: str,
    public_title: str = Form(...),
    working_title: str = Form(""),
    theme: str = Form(""),
    story: str = Form(""),
    status: str = Form(...),
):
    update_artwork(
        artwork_code=artwork_code,
        public_title=public_title,
        working_title=working_title,
        theme=theme,
        story=story,
        status=status,
    )

    artwork = get_artwork(artwork_code)

    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context={
            "artwork": artwork,
            "saved": True,
        },
    )



