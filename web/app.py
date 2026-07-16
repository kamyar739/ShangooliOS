from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette import status

from app.database import create_artwork as create_artwork_with_workspace
from web.db import (
    archive_artwork,
    archive_collection,
    create_collection,
    get_artwork,
    get_collection,
    get_collections,
    restore_artwork,
    update_artwork,
    update_collection,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ShangooliOS")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"collections": get_collections()},
    )


@app.get("/collections/new")
def new_collection_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="new_collection.html",
        context={},
    )


@app.post("/collections/new")
def create_collection_post(
    code: str = Form(...),
    name: str = Form(...),
    target_artwork_count: int = Form(0),
    collection_status: str = Form("planned"),
):
    collection_code = create_collection(
        code=code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
    )
    return RedirectResponse(
        url=f"/collections/{collection_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}")
def collection_page(request: Request, collection_code: str):
    collection, artworks, archived_artworks = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="collection.html",
        context={
            "collection": collection,
            "artworks": artworks,
            "archived_artworks": archived_artworks,
        },
    )


@app.get("/collections/{collection_code}/edit")
def edit_collection_form(request: Request, collection_code: str):
    collection, _, _ = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="edit_collection.html",
        context={"collection": collection},
    )


@app.post("/collections/{collection_code}/edit")
def edit_collection_post(
    collection_code: str,
    name: str = Form(...),
    target_artwork_count: int = Form(0),
    collection_status: str = Form(...),
):
    update_collection(
        collection_code=collection_code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
    )
    return RedirectResponse(
        url=f"/collections/{collection_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/archive")
def archive_collection_post(collection_code: str):
    archive_collection(collection_code)
    return RedirectResponse(
        url="/",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}/new")
def new_artwork_form(request: Request, collection_code: str):
    collection, _, _ = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="new_artwork.html",
        context={"collection": collection},
    )


@app.post("/collections/{collection_code}/new")
def create_artwork_post(
    collection_code: str,
    public_title: str = Form(...),
    working_title: str = Form(""),
    theme: str = Form(""),
):
    result = create_artwork_with_workspace(
        collection_code=collection_code,
        public_title=public_title,
        working_title=working_title,
        theme=theme,
    )
    return RedirectResponse(
        url=f"/artworks/{result['artwork_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
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
    status_value: str = Form(..., alias="status"),
):
    update_artwork(
        artwork_code=artwork_code,
        public_title=public_title,
        working_title=working_title,
        theme=theme,
        story=story,
        status=status_value,
    )

    artwork = get_artwork(artwork_code)

    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context={"artwork": artwork, "saved": True},
    )


@app.post("/artworks/{artwork_code}/archive")
def archive_artwork_post(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    archive_artwork(artwork_code)

    return RedirectResponse(
        url=f"/collections/{artwork['collection_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/restore")
def restore_artwork_post(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    restore_artwork(artwork_code)

    return RedirectResponse(
        url=f"/collections/{artwork['collection_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
